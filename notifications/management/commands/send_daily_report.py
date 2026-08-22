from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import Company
from notifications.mailer import send_daily_report, smtp_connection
from notifications.models import DeliveryLog, MailingList


class Command(BaseCommand):
    help = "发送公司当日经营日报邮件；建议由 Windows 计划任务每 10 分钟触发一次。"

    # SMTP 故障时每 10 分钟重试一次就是一天 144 次，每次都要重建报表、重算
    # 工作簿，还要各阻塞 EMAIL_TIMEOUT=30 秒。试够次数就停手，等人来看日志，
    # 修好后用 --force 补发。
    MAX_DAILY_ATTEMPTS = 5

    def add_arguments(self, parser):
        parser.add_argument("--date", help="业务日期 YYYY-MM-DD，默认取今天。")
        parser.add_argument("--company", help="只发送指定公司代码，默认全部启用公司。")
        parser.add_argument("--list-id", type=int, help="只发送指定收件组编号，用于手工补发。")
        parser.add_argument("--now", action="store_true", help="忽略收件组的发送时间，立即发送。")
        parser.add_argument("--force", action="store_true", help="当天已成功发送过也重新发送。")
        parser.add_argument("--allow-empty", action="store_true", help="当天没有数据也照常发送。")
        parser.add_argument("--dry-run", action="store_true", help="只打印将要发送的收件组，不实际发信。")

    def handle(self, *args, **options):
        report_date = self._resolve_date(options["date"])
        mailing_lists = MailingList.objects.filter(is_active=True, company__is_active=True).select_related("company")
        if options["company"]:
            company = Company.objects.filter(code=options["company"]).first()
            if company is None:
                raise CommandError(f"找不到公司代码 {options['company']}")
            mailing_lists = mailing_lists.filter(company=company)
        if options["list_id"]:
            mailing_lists = mailing_lists.filter(pk=options["list_id"])

        due = [item for item in mailing_lists if self._is_due(item, report_date, options)]
        if not due:
            self.stdout.write("没有到点或待发送的收件组。")
            return

        if options["dry_run"]:
            for item in due:
                self.stdout.write(f"[dry-run] {item} → {', '.join(item.recipient_list())}")
            return

        connection = smtp_connection()
        sent = 0
        for item in due:
            ok, detail = send_daily_report(
                item,
                report_date,
                connection=connection,
                skip_when_empty=not options["allow_empty"],
            )
            sent += 1 if ok else 0
            self.stdout.write(f"{'[成功]' if ok else '[跳过/失败]'} {item}：{detail}")
        self.stdout.write(f"完成：{sent}/{len(due)} 个收件组发送成功。")

    def _resolve_date(self, value):
        if not value:
            return timezone.localdate()
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            raise CommandError("--date 需要 YYYY-MM-DD 格式") from None

    def _is_due(self, mailing_list, report_date, options):
        """到点判断留有余量：计划任务每 10 分钟跑一次，只要过了发送时间且当天没成功过就发。

        --force 会绕过成功记录和失败次数上限，用于修好 SMTP 后手工补发。
        """
        if options["force"]:
            return True
        logs = DeliveryLog.objects.filter(mailing_list=mailing_list, report_date=report_date)
        if logs.filter(status=DeliveryLog.Status.SENT).exists():
            return False
        failures = logs.filter(status=DeliveryLog.Status.FAILED).count()
        if failures >= self.MAX_DAILY_ATTEMPTS:
            self.stdout.write(
                self.style.WARNING(
                    f"[已放弃] {mailing_list}：今天失败 {failures} 次，已达上限 "
                    f"{self.MAX_DAILY_ATTEMPTS} 次，不再重试。"
                    "请查看 logs/mail.log 排查，修好后用 --force 补发。"
                )
            )
            return False
        if options["now"]:
            return True
        return timezone.localtime().time() >= mailing_list.send_at
