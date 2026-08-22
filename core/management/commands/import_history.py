"""把 data/newsource 下的历史数据导入指定公司。

用法：
    python manage.py import_history --company FNS --dry-run
    python manage.py import_history --company FNS --password '初始密码'
    python manage.py import_history --company FNS --reset --yes-i-know

设计取舍：业务员/采购员的用户名要用全拼，而通用导入器是按源表里的中文名
直接建号的。所以这里先按姓名映射表建好账号，再让导入器复用同名账号。

姓名映射表含真实员工信息，不进版本库，默认从 data/newsource/people.json
读取（格式见 docs/import-people.example.json）。初始密码通过 --password
或环境变量 IMPORT_DEFAULT_PASSWORD 传入，不写在代码里。
"""

import json
import os
from pathlib import Path

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.excel import read_rows
from core.models import Company, Customer, ExchangeRate, PurchaseAssignment, SalesAssignment, Supplier
from core.services.companies import grant_company_access
from core.services.master_data import save_exchange_rate
from purchase.importers import commit_purchase_import, preview_purchase_import
from sales.importers import commit_sales_import, preview_sales_import


PEOPLE_FILE = "data/newsource/people.json"
SALES_FILE = "data/newsource/sale.xls"
PURCHASE_FILE = "data/newsource/purchase.xls"


class Command(BaseCommand):
    help = "导入 data/newsource 下的销售与采购历史数据"

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True, help="目标公司代码，例如 FNS")
        parser.add_argument("--dry-run", action="store_true", help="只预览校验结果，不写库")
        parser.add_argument(
            "--reset",
            action="store_true",
            help="先清空该公司的日报、客户、供应商、归属和汇率，再导入（用于重跑）",
        )
        parser.add_argument(
            "--yes-i-know",
            action="store_true",
            help="确认执行 --reset 的删除操作。不加此参数时 --reset 只打印将删除的数量并退出。",
        )
        parser.add_argument(
            "--password",
            help="新建账号的初始密码。不传则读环境变量 IMPORT_DEFAULT_PASSWORD。",
        )
        parser.add_argument("--people-file", default=PEOPLE_FILE, help="中文姓名到登录名的映射 JSON")
        parser.add_argument("--sales-file", default=SALES_FILE)
        parser.add_argument("--purchase-file", default=PURCHASE_FILE)

    def handle(self, *args, **options):
        company = Company.objects.filter(code=options["company"]).first()
        if company is None:
            raise CommandError(f"找不到公司代码 {options['company']}")

        actor = User.objects.filter(is_superuser=True).order_by("pk").first()
        if actor is None:
            raise CommandError("需要至少一个超级用户作为操作人（审计日志要记录操作人）")

        people_map = self._load_people_map(options["people_file"])
        password = options["password"] or os.getenv("IMPORT_DEFAULT_PASSWORD")

        self.stdout.write(f"目标公司：{company.name}（{company.code}）")
        self.stdout.write(f"操作人：{actor.username}")

        # --reset 会按公司删掉全部业务数据，误敲一次就是数据清零，
        # 所以默认只报数不动手，必须显式加 --yes-i-know 才真删。
        if options["reset"] and not options["yes_i_know"]:
            self._preview_reset(company, people_map)
            raise CommandError("以上数据将被删除。确认无误后重跑并加上 --yes-i-know。")

        sales_preview = preview_sales_import(options["sales_file"])
        self._report("销售", sales_preview, extra=sales_preview.rate_errors)
        purchase_preview = preview_purchase_import(options["purchase_file"], company=company)
        self._report("采购", purchase_preview, extra=purchase_preview.rate_errors)

        blocking = list(sales_preview.error_rows) + list(purchase_preview.error_rows)
        if blocking:
            raise CommandError("预览存在错误行，已中止。请先修正源数据。")

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("dry-run：未写入任何数据"))
            return

        sales_names = {row["owner_name"] for row in sales_preview.rows}
        purchase_names = {row["buyer_name"] for row in purchase_preview.rows}

        # 建号要用到密码，但只有真的会新建账号时才强制要求，
        # 否则重跑一次已建好的导入也会被拦下来。
        if not password and self._needs_new_account(people_map, sales_names | purchase_names):
            raise CommandError(
                "需要为新账号设置初始密码：加 --password '密码' 或设环境变量 IMPORT_DEFAULT_PASSWORD"
            )

        with transaction.atomic():
            if options["reset"]:
                self._reset(company, people_map)
            people = self._create_accounts(company, sales_names, purchase_names, people_map, password)
            rates = self._import_rates(options["sales_file"], company=company, actor=actor)
            self.stdout.write(f"汇率：写入/更新 {rates} 条")

            sales_count = commit_sales_import(
                sales_preview,
                actor=actor,
                company=company,
                source_file="newsource/sale.xls",
                people=people,
            )
            self.stdout.write(f"销售日报：导入 {sales_count} 条")

            purchase_count = commit_purchase_import(
                purchase_preview,
                actor=actor,
                company=company,
                source_file="newsource/purchase.xls",
                people=people,
            )
            self.stdout.write(f"采购日报：导入 {purchase_count} 条")

        self._summarise(company)

    def _load_people_map(self, path):
        """读取 {中文姓名: 登录名} 映射。真实员工姓名不进版本库，所以放外部文件。"""
        people_file = Path(path)
        if not people_file.exists():
            raise CommandError(
                f"找不到人员映射文件 {path}。"
                "请按 docs/import-people.example.json 的格式创建（该文件不进版本库）。"
            )
        try:
            mapping = json.loads(people_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise CommandError(f"人员映射文件 {path} 不是合法 JSON：{error}") from None
        if not isinstance(mapping, dict) or not mapping:
            raise CommandError(f"人员映射文件 {path} 应是形如 {{\"中文姓名\": \"loginname\"}} 的非空对象")
        # 下划线开头的键是示例文件里的说明文字，不是人名。
        return {name: login for name, login in mapping.items() if not name.startswith("_")}

    def _needs_new_account(self, people_map, chinese_names):
        usernames = [people_map[name] for name in chinese_names if name in people_map]
        existing = set(User.objects.filter(username__in=usernames).values_list("username", flat=True))
        return any(username not in existing for username in usernames)

    def _report(self, label, preview, extra=None):
        self.stdout.write(f"\n[{label}] 有效行 {preview.valid_row_count}，错误行 {len(preview.error_rows)}")
        for error in preview.error_rows[:20]:
            self.stdout.write(f"    第{error['row_number']}行 {error['field']}：{error['message']}")
        for error in (extra or [])[:20]:
            self.stdout.write(f"    [汇率提示] 第{error['row_number']}行：{error['message']}")

    def _create_accounts(self, company, sales_names, purchase_names, people_map, password):
        """按登录名建号挂角色，返回 {中文姓名: User} 供导入器使用。
        必须返回映射：导入器默认拿源表里的中文姓名当用户名，
        不传映射就会另外建一批中文名账号，日报也会挂到那些账号上。"""
        sales_group = Group.objects.get(name="sales")
        purchase_group = Group.objects.get(name="purchase")
        people = {}
        created = 0
        for chinese_name in sorted(sales_names | purchase_names):
            username = people_map.get(chinese_name)
            if username is None:
                raise CommandError(f"人员「{chinese_name}」没有对应的登录名，请先补进人员映射文件")
            user, is_new = User.objects.get_or_create(
                username=username, defaults={"first_name": chinese_name}
            )
            if is_new:
                user.set_password(password)
                user.first_name = chinese_name
                user.save(update_fields=["password", "first_name"])
                created += 1
            if chinese_name in sales_names:
                user.groups.add(sales_group)
            if chinese_name in purchase_names:
                user.groups.add(purchase_group)
            grant_company_access(user, [company])
            from core.models import UserProfile

            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.must_change_password = True
            profile.save(update_fields=["must_change_password"])
            people[chinese_name] = user
        self.stdout.write(f"账号：新建 {created} 个，共处理 {len(people)} 人")
        return people

    def _reset_targets(self, company, people_map):
        """返回 --reset 会删掉的东西：各类业务数据的 queryset，以及待删的空账号。"""
        from purchase.models import PurchaseReceipt
        from sales.models import SalesShipment

        querysets = {
            "销售日报": SalesShipment.objects.filter(company=company),
            "采购日报": PurchaseReceipt.objects.filter(company=company),
            "销售归属": SalesAssignment.objects.filter(customer__company=company),
            "采购归属": PurchaseAssignment.objects.filter(supplier__company=company),
            "客户": Customer.objects.filter(company=company),
            "供应商": Supplier.objects.filter(company=company),
            "汇率": ExchangeRate.objects.filter(company=company),
        }
        # 页面导入不传映射时会按中文姓名建号，这里清掉那批没人登录过的旧账号。
        stale = [
            user
            for user in User.objects.filter(username__in=people_map.keys())
            if not user.last_login and not user.is_superuser
        ]
        return querysets, stale

    def _preview_reset(self, company, people_map):
        """只报数不删，给 --reset 前的确认用。"""
        querysets, stale = self._reset_targets(company, people_map)
        self.stdout.write(self.style.WARNING(f"\n--reset 将从「{company.name}」删除："))
        for label, queryset in querysets.items():
            self.stdout.write(f"    {label}：{queryset.count()} 条")
        if stale:
            self.stdout.write(f"    中文名旧账号：{len(stale)} 个（{'、'.join(u.username for u in stale)}）")

    def _reset(self, company, people_map):
        """清空该公司的业务数据，并删掉之前用中文姓名建的、没人用的空账号。
        只删这家公司的数据，不动其它公司，也不动有登录记录的账号。"""
        querysets, stale = self._reset_targets(company, people_map)
        counts = {label: queryset.delete()[0] for label, queryset in querysets.items()}
        self.stdout.write("清空：" + "，".join(f"{k} {v}" for k, v in counts.items()))

        if stale:
            names = [user.username for user in stale]
            for user in stale:
                user.delete()
            self.stdout.write(f"删除中文名旧账号 {len(names)} 个：{'、'.join(names)}")

    def _import_rates(self, path, *, company, actor):
        from sales.importers import validate_exchange_rate_rows

        errors, rates = validate_exchange_rate_rows(read_rows(path, "汇率"))
        if errors:
            raise CommandError(f"汇率表有 {len(errors)} 行无效")
        for rate in rates:
            existing = ExchangeRate.objects.filter(company=company, month=rate["month"]).first()
            save_exchange_rate(
                actor=actor,
                company=company,
                instance=existing,
                data={"month": rate["month"], "usd_to_cny": rate["usd_to_cny"]},
            )
        return len(rates)

    def _summarise(self, company):
        from purchase.models import PurchaseReceipt
        from sales.models import SalesShipment

        self.stdout.write("\n=== 导入后统计 ===")
        self.stdout.write(f"客户：{Customer.objects.filter(company=company).count()}")
        self.stdout.write(f"供应商：{Supplier.objects.filter(company=company).count()}")
        self.stdout.write(f"汇率：{ExchangeRate.objects.filter(company=company).count()}")
        self.stdout.write(f"销售归属：{SalesAssignment.objects.filter(customer__company=company).count()}")
        self.stdout.write(f"采购归属：{PurchaseAssignment.objects.filter(supplier__company=company).count()}")
        sales = SalesShipment.objects.filter(company=company)
        purchase = PurchaseReceipt.objects.filter(company=company)
        self.stdout.write(f"销售日报：{sales.count()} 条")
        self.stdout.write(f"采购日报：{purchase.count()} 条")
