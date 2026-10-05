"""报表生成与推送命令：生成快照、发送邮件与钉钉群消息。

沿用现有每 10 分钟检查到点任务，集成金额对账、次日更正和失败重试。

用法：
    python manage.py generate_and_send_report --date 2026-10-04 --company COMPANY_CODE
    python manage.py generate_and_send_report --now  # 生成今天报表并立即发送
"""

from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import Company
from integrations.services.report_delivery import (
    generate_report_snapshot,
    send_report_to_all_channels,
)


class Command(BaseCommand):
    help = "生成报表快照并推送到邮件和钉钉群"

    def add_arguments(self, parser):
        parser.add_argument("--date", help="报表日期 YYYY-MM-DD，默认取前一自然日")
        parser.add_argument("--company", help="仅生成指定公司代码的报表")
        parser.add_argument("--scope", choices=["SALES", "PURCHASE", "BOTH"], default="BOTH", help="业务范围")
        parser.add_argument("--now", action="store_true", help="立即发送，忽略收件组发送时间")
        parser.add_argument("--force", action="store_true", help="强制重新生成快照，即使已存在")
        parser.add_argument("--dry-run", action="store_true", help="只生成快照，不实际发送")

    def handle(self, *args, **options):
        # 解析报表日期：默认前一自然日
        if options["date"]:
            try:
                report_date = datetime.strptime(options["date"], "%Y-%m-%d").date()
            except ValueError:
                raise CommandError("--date 需要 YYYY-MM-DD 格式") from None
        else:
            from datetime import timedelta
            report_date = timezone.localdate() - timedelta(days=1)

        # 解析公司
        companies = Company.objects.filter(is_active=True)
        if options["company"]:
            companies = companies.filter(code=options["company"])
            if not companies.exists():
                raise CommandError(f"找不到公司代码：{options['company']}")

        scope = options["scope"]

        # 逐公司生成快照和推送
        for company in companies:
            self.stdout.write(self.style.MIGRATE_HEADING(f"== {company.name} =="))

            try:
                # 生成或获取快照
                snapshot = generate_report_snapshot(
                    company=company,
                    report_date=report_date,
                    scope=scope,
                    force_regenerate=options["force"],
                )

                self.stdout.write(
                    self.style.SUCCESS(
                        f"快照生成完成：#{snapshot.id} "
                        f"({'完整' if snapshot.is_complete else '不完整'})"
                    )
                )

                if snapshot.sync_warnings:
                    for warning in snapshot.sync_warnings:
                        self.stdout.write(self.style.WARNING(f"  警告：{warning}"))

                # 推送到各渠道
                if not options["dry_run"]:
                    results = send_report_to_all_channels(
                        snapshot=snapshot,
                        send_now=options["now"],
                    )

                    for channel, status, message in results:
                        if status == "SENT":
                            self.stdout.write(self.style.SUCCESS(f"  {channel}: 发送成功"))
                        elif status == "SKIPPED":
                            self.stdout.write(f"  {channel}: 跳过 - {message}")
                        else:
                            self.stdout.write(self.style.ERROR(f"  {channel}: 失败 - {message}"))
                else:
                    self.stdout.write("  [dry-run] 跳过实际发送")

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  失败：{e}"))
                if options.get("verbosity", 1) > 1:
                    import traceback
                    self.stdout.write(traceback.format_exc())

        self.stdout.write(self.style.SUCCESS("完成"))
