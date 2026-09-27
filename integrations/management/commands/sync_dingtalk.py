"""同步钉钉审批实例（付款申请等）到本地。建议每晚 20:00 触发（命令幂等）。"""

from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import Company
from integrations.models import SyncRun
from integrations.services.dingtalk_sync import sync_dingtalk
from integrations.services.kingdee_sync import has_synced_today


class Command(BaseCommand):
    help = "同步钉钉 OA 审批实例（付款申请等）到本地。"

    def add_arguments(self, parser):
        parser.add_argument("--date", help="以哪天为基准(YYYY-MM-DD)，默认今天。")
        parser.add_argument("--company", help="仅同步指定公司代码，缺省同步全部。")
        parser.add_argument("--force", action="store_true", help="忽略当天已同步判断，强制重跑。")
        parser.add_argument("--dry-run", action="store_true", help="只统计条数，不写库。")

    def handle(self, *args, **options):
        as_of = None
        if options["date"]:
            try:
                as_of = datetime.strptime(options["date"], "%Y-%m-%d").date()
            except ValueError as exc:
                raise CommandError(f"日期格式应为 YYYY-MM-DD：{exc}") from exc

        company = None
        if options["company"]:
            try:
                company = Company.objects.get(code=options["company"])
            except Company.DoesNotExist as exc:
                raise CommandError(f"找不到公司代码：{options['company']}") from exc

        on = as_of or timezone.localdate()
        if not options["force"] and not options["dry_run"] and has_synced_today(SyncRun.Integration.DINGTALK, company, on):
            self.stdout.write(self.style.WARNING(f"{on} 钉钉已同步过，跳过（--force 可强制）。"))
            return

        results = sync_dingtalk(as_of=as_of, company=company, dry_run=options["dry_run"])
        if not results:
            self.stdout.write(self.style.WARNING("没有启用的钉钉应用，未执行同步。"))
            return
        for r in results:
            if r["error"]:
                self.stdout.write(self.style.ERROR(f"[{r['company']}] 失败：{r['error']}"))
            else:
                self.stdout.write(self.style.SUCCESS(
                    f"[{r['company']}] 同步 {r['upserted']} 条审批" + ("（dry-run 未写库）" if options["dry_run"] else "")
                ))
