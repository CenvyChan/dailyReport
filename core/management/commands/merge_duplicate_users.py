"""把导入时误建的「中文姓名账号」合并回正确的登录账号。

背景：页面导入曾经按源表姓名直接建号，而系统里的账号是拼音/工号登录名，
中文姓名只存在 first_name 里。结果同一个业务员被拆成两个账号，日报和客户
归属也被拆开。这个命令把数据迁回正确账号，再删掉空壳账号。

用法：
    # 只打印将要合并的账号和影响行数，不写库
    python manage.py merge_duplicate_users

    # 自动匹配（按 first_name）后执行
    python manage.py merge_duplicate_users --apply

    # 自动匹配不到的，用显式映射指定目标登录名；目标不存在时创建
    python manage.py merge_duplicate_users --apply \
        --map 腾琼=tengqiong --map 滕琼=tengqiong \
        --target-name tengqiong=滕琼 --create-missing

命令是幂等的：重复执行时，已合并的源账号不存在，只会报告「无需处理」。
"""

import re

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import (
    CompanyMembership,
    PurchaseAssignment,
    SalesAssignment,
    UserProfile,
)
from core.services.audit import record_audit
from core.services.users import normalize_person_name
from purchase.models import PurchaseReceipt
from sales.models import SalesShipment


CHINESE_NAME = re.compile(r"[\u4e00-\u9fff]")


class Command(BaseCommand):
    help = "把导入时误建的中文姓名账号合并回正确的登录账号"

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="真正执行合并。不加时只做 dry-run，打印将迁移的行数。",
        )
        parser.add_argument(
            "--map",
            action="append",
            default=[],
            metavar="源姓名=目标登录名",
            help="显式指定合并目标，可重复。用于 first_name 匹配不到的姓名。",
        )
        parser.add_argument(
            "--target-name",
            action="append",
            default=[],
            metavar="登录名=姓名",
            help="新建目标账号时使用的姓名（first_name），可重复。",
        )
        parser.add_argument(
            "--create-missing",
            action="store_true",
            help="目标登录名不存在时创建账号（密码不可用，只作为数据归属人）。",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="允许合并已设置密码或有登录记录的账号。默认跳过，避免误删真人账号。",
        )

    def handle(self, *args, **options):
        self.apply = options["apply"]
        self.force = options["force"]
        self.create_missing = options["create_missing"]
        self.explicit_maps = self._parse_pairs(options["map"], "--map")
        self.target_names = self._parse_pairs(options["target_name"], "--target-name")

        plans, skipped = self._build_plans()
        for item in skipped:
            self.stdout.write(self.style.WARNING(f"跳过 {item}"))
        if not plans:
            self.stdout.write("没有需要合并的账号。")
            return

        self.stdout.write("将执行以下合并：")
        total = {"sales": 0, "purchase": 0, "sales_as": 0, "purchase_as": 0}
        for plan in plans:
            counts = self._count_references(plan["source"])
            total["sales"] += counts["sales"]
            total["purchase"] += counts["purchase"]
            total["sales_as"] += counts["sales_as"]
            total["purchase_as"] += counts["purchase_as"]
            target_label = (
                f"新建 {plan['target_username']}（{plan['target_name']}）"
                if plan["create_target"]
                else f"{plan['target'].username}（{plan['target'].first_name or '无姓名'}）"
            )
            self.stdout.write(
                f"  {plan['source'].username}(id={plan['source'].pk}) -> {target_label}："
                f"销售 {counts['sales']} 行，采购 {counts['purchase']} 行，"
                f"客户归属 {counts['sales_as']}，供应商归属 {counts['purchase_as']}"
            )
        self.stdout.write(
            f"合计：销售 {total['sales']} 行，采购 {total['purchase']} 行，"
            f"客户归属 {total['sales_as']}，供应商归属 {total['purchase_as']}"
        )

        if not self.apply:
            self.stdout.write(self.style.WARNING("这是 dry-run，未写入任何数据。确认后加 --apply 执行。"))
            return

        actor = User.objects.filter(is_superuser=True, is_active=True).order_by("pk").first()
        for plan in plans:
            self._merge(plan, actor)
        self.stdout.write(self.style.SUCCESS(f"已合并 {len(plans)} 个账号。"))

    # ---- 计划 ----

    def _parse_pairs(self, values, option):
        pairs = {}
        for value in values:
            source, separator, target = value.partition("=")
            source, target = source.strip(), target.strip()
            if not separator or not source or not target:
                raise CommandError(f"{option} 的格式应为 源=目标，收到：{value}")
            pairs[source] = target
        return pairs

    def _build_plans(self):
        plans = []
        skipped = []
        handled = set()
        index = self._first_name_index()

        for source_name, target_username in self.explicit_maps.items():
            source = User.objects.filter(username=source_name).first()
            if source is None:
                skipped.append(f"{source_name}：系统中已没有该账号（可能已合并过）")
                continue
            handled.add(source.pk)
            plan, reason = self._plan_for(source, target_username)
            if plan:
                plans.append(plan)
            else:
                skipped.append(f"{source.username}：{reason}")

        for source in User.objects.order_by("pk"):
            if source.pk in handled or not CHINESE_NAME.search(source.username or ""):
                continue
            target_username, reason = self._guess_target(source, index)
            if target_username is None:
                skipped.append(f"{source.username}：{reason}")
                continue
            plan, reason = self._plan_for(source, target_username)
            if plan:
                plans.append(plan)
            else:
                skipped.append(f"{source.username}：{reason}")
        return plans, skipped

    def _first_name_index(self):
        index = {}
        for user in User.objects.order_by("pk"):
            key = normalize_person_name(user.first_name)
            if key:
                index.setdefault(key, []).append(user)
        return index

    def _guess_target(self, source, index):
        candidates = [
            user
            for user in index.get(normalize_person_name(source.username), [])
            if user.pk != source.pk
        ]
        if not candidates:
            return None, "没有 first_name 相同的账号，请用 --map 指定目标"
        if len(candidates) > 1:
            names = "、".join(f"{user.username}" for user in candidates)
            return None, f"姓名匹配到多个账号（{names}），请用 --map 明确指定目标"
        return candidates[0].username, ""

    def _plan_for(self, source, target_username):
        if source.username == target_username:
            return None, "源账号与目标账号相同"
        if not self.force:
            if source.is_superuser or source.is_staff:
                return None, "是管理员/员工账号，确认要合并请加 --force"
            # 注意不能用 has_usable_password()：空字符串密码在 Django 里算「可用」，
            # 而导入误建的账号正是 password=""。用非空密码或有过登录来判断真人账号。
            if source.password or source.last_login:
                return None, "已设置密码或有登录记录，确认要合并请加 --force"
        target = User.objects.filter(username=target_username).first()
        if target is None and not self.create_missing:
            return None, f"目标账号 {target_username} 不存在，确认要新建请加 --create-missing"
        return {
            "source": source,
            "target": target,
            "target_username": target_username,
            "target_name": self.target_names.get(target_username, target_username),
            "create_target": target is None,
        }, ""

    def _count_references(self, source):
        return {
            "sales": SalesShipment.objects.filter(owner=source).count(),
            "purchase": PurchaseReceipt.objects.filter(buyer=source).count(),
            "sales_as": SalesAssignment.objects.filter(user=source).count(),
            "purchase_as": PurchaseAssignment.objects.filter(user=source).count(),
        }

    # ---- 执行 ----

    @transaction.atomic
    def _merge(self, plan, actor):
        source = plan["source"]
        target = plan["target"]
        if target is None:
            # 多个源账号可能映射到同一个新目标（如「腾琼」「滕琼」→ tengqiong），
            # 同一次运行里第二个要复用第一个已建好的账号。
            target = User.objects.filter(username=plan["target_username"]).first()
        if target is None:
            target = User.objects.create(
                username=plan["target_username"], first_name=plan["target_name"]
            )
            plan["target"] = target

        counts = self._count_references(source)
        SalesShipment.objects.filter(owner=source).update(owner=target)
        PurchaseReceipt.objects.filter(buyer=source).update(buyer=target)

        SalesAssignment.objects.bulk_create(
            [
                SalesAssignment(user=target, customer_id=customer_id)
                for customer_id in SalesAssignment.objects.filter(user=source).values_list(
                    "customer_id", flat=True
                )
            ],
            ignore_conflicts=True,
        )
        PurchaseAssignment.objects.bulk_create(
            [
                PurchaseAssignment(user=target, supplier_id=supplier_id)
                for supplier_id in PurchaseAssignment.objects.filter(user=source).values_list(
                    "supplier_id", flat=True
                )
            ],
            ignore_conflicts=True,
        )
        SalesAssignment.objects.filter(user=source).delete()
        PurchaseAssignment.objects.filter(user=source).delete()

        target.groups.add(*source.groups.all())
        CompanyMembership.objects.bulk_create(
            [
                CompanyMembership(user=target, company_id=company_id)
                for company_id in CompanyMembership.objects.filter(user=source).values_list(
                    "company_id", flat=True
                )
            ],
            ignore_conflicts=True,
        )
        CompanyMembership.objects.filter(user=source).delete()
        UserProfile.objects.filter(user=source).delete()

        record_audit(
            actor=actor,
            instance=target,
            action="MERGE",
            before={"merged_username": source.username, "merged_id": source.pk},
            after={
                "username": target.username,
                "first_name": target.first_name,
                **{f"moved_{key}": value for key, value in counts.items()},
            },
        )
        source.delete()
