"""回填钉钉审批发起人姓名，并刷新已有支出报表快照的申请人。

安全边界：
- 只写 `originator_name` 一个字段，用 queryset.update 绕过 auto_now，
  不改状态、金额、时间、raw 或组织归属，也不触发任何同步/推送。
- 默认 dry-run；`--apply` 才写库。
- 快照只替换明细里为空的 `originator`，写库前对比除该字段外的整份 JSON，
  确认金额、笔数、状态、排序完全没变，才允许保存；保存后只刷新
  `generated_at` 以失效旧 PDF 缓存，快照 ID 和签名链接保持不变。
"""

import json
from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from integrations.models import DingtalkApprovalInstance, DingtalkApp, PaymentReportSnapshot
from integrations.services.dingtalk_client import DingtalkClient
from integrations.services.payment_organizations import approval_scope
from integrations.services.user_names import UserNameDirectory, name_from_title


def _detail_rows(data):
    for group in data.get("by_recipient") or []:
        yield from group.get("details") or []


def _without_originator(data):
    """比较快照数据时忽略 originator，确保回填没有动到别的字段。"""
    clone = json.loads(json.dumps(data, ensure_ascii=False))
    for detail in _detail_rows(clone):
        detail.pop("originator", None)
    return clone


class Command(BaseCommand):
    help = "回填审批发起人姓名（默认 dry-run），并刷新已有支出报表快照中的申请人"

    def add_arguments(self, parser):
        parser.add_argument("--company", help="仅处理该组织代码，缺省全部")
        parser.add_argument("--apply", action="store_true", help="实际写库；缺省只统计不修改")
        parser.add_argument("--skip-snapshots", action="store_true", help="只回填审批表，不改已有快照")
        parser.add_argument("--limit", type=int, default=0, help="最多处理多少张审批（调试用，0 表示全部）")

    def handle(self, *args, **options):
        apply = options["apply"]
        self.stdout.write("模式：" + ("APPLY（会写库）" if apply else "DRY-RUN（只读）"))

        names_by_process = self._approval_names(options)
        if not options["skip_snapshots"]:
            self._refresh_snapshots(options.get("company"), apply, names_by_process)

        if not apply:
            self.stdout.write(self.style.WARNING("未写库。确认上面的统计后加 --apply 执行。"))

    def _approval_names(self, options):
        apply = options["apply"]
        apps = DingtalkApp.objects.filter(is_active=True).select_related("company")
        if options.get("company"):
            apps = apps.filter(
                company__code=options["company"]
            ) | apps.filter(company_mappings__company__code=options["company"])
            apps = apps.distinct()
        if not apps:
            raise CommandError("没有匹配的启用钉钉应用")

        stats = Counter()
        mismatches = []
        names_by_process = {}
        seen = set()
        for app in apps:
            client = DingtalkClient(app)
            directory = UserNameDirectory(client)
            rows = [
                row
                for row in approval_scope(app)
                .filter(Q(originator_name="") | Q(originator_name__isnull=True))
                .order_by("pk")
                if row.pk not in seen
            ]
            if options.get("limit"):
                rows = rows[: options["limit"]]
            # 多个应用可能映射到同一组织，同一张审批只处理一次。
            seen.update(row.pk for row in rows)
            self.stdout.write(f"\n应用 {app.company.code} / {app.name or '(未命名)'}：待回填 {len(rows)} 条")
            for row in rows:
                raw = dict(row.raw or {})
                raw.setdefault("originator_userid", row.originator_userid)
                raw.setdefault("title", row.title)
                name = directory.originator_name(raw)
                title_name = name_from_title(row.title)
                if not name:
                    stats["未解析"] += 1
                    continue
                if title_name and title_name != name:
                    mismatches.append((row.process_instance_id, title_name, name))
                if apply:
                    # update() 不触发 auto_now，避免打乱按 updated_at 取最新源端的既有逻辑。
                    DingtalkApprovalInstance.objects.filter(pk=row.pk).update(originator_name=name)
                stats["已回填"] += 1
                names_by_process.setdefault(row.company_id, {})[row.process_instance_id] = name

        self.stdout.write(
            f"\n审批回填汇总：应回填 {stats['已回填']} 条，未解析 {stats['未解析']} 条"
        )
        if mismatches:
            self.stdout.write(self.style.WARNING(
                f"标题人名与通讯录不一致 {len(mismatches)} 条（以通讯录为准），样例："
            ))
            for pid, title_name, api_name in mismatches[:10]:
                self.stdout.write(f"  {pid}: 标题「{title_name}」≠ 通讯录「{api_name}」")
        return names_by_process

    def _refresh_snapshots(self, company_code, apply, resolved=None):
        snapshots = PaymentReportSnapshot.objects.all()
        if company_code:
            snapshots = snapshots.filter(company__code=company_code)
        snapshots = snapshots.order_by("pk")
        if not snapshots:
            self.stdout.write("\n没有匹配的支出报表快照")
            return

        # 快照按公司隔离，同一实例ID在不同公司下可能是不同记录，键必须带公司。
        # 先用本次解析结果（dry-run 也有值），再补库里已有的姓名。
        name_index = {
            (company_id, pid): name
            for company_id, rows in (resolved or {}).items()
            for pid, name in rows.items()
        }
        for row in DingtalkApprovalInstance.objects.exclude(originator_name="").values(
            "company_id", "process_instance_id", "originator_name"
        ):
            name_index.setdefault((row["company_id"], row["process_instance_id"]), row["originator_name"])

        total_changed = 0
        for snapshot in snapshots:
            data = json.loads(json.dumps(snapshot.data or {}, ensure_ascii=False))
            changed = 0
            blank = 0
            for detail in _detail_rows(data):
                if (detail.get("originator") or "").strip():
                    continue
                name = name_index.get((snapshot.company_id, detail.get("process_instance_id")))
                if name:
                    detail["originator"] = name
                    changed += 1
                else:
                    blank += 1
            if not changed:
                self.stdout.write(
                    f"快照 #{snapshot.pk} {snapshot.company.code} {snapshot.report_type} "
                    f"{snapshot.period_label}：无需刷新（仍空 {blank} 条）"
                )
                continue

            # 除 originator 外必须完全一致，否则宁可中止也不污染冻结数据。
            if _without_originator(data) != _without_originator(snapshot.data):
                raise CommandError(f"快照 #{snapshot.pk} 回填会改动申请人以外的字段，已中止")

            self.stdout.write(
                f"快照 #{snapshot.pk} {snapshot.company.code} {snapshot.report_type} "
                f"{snapshot.period_label}：回填 {changed} 条"
                + (f"，仍空 {blank} 条（无对应审批）" if blank else "")
            )
            if apply:
                snapshot.data = data
                snapshot.generated_at = timezone.now()
                snapshot.save(update_fields=["data", "generated_at"])
            total_changed += changed
        self.stdout.write(f"\n快照回填汇总：{'已写入' if apply else '将写入'} {total_changed} 条明细")
