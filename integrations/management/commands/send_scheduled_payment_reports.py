"""按群配置投递到期付款报表；一个群可选择多个公司。"""

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from integrations.models import DingtalkGroupConfig, PaymentReportDispatch
from integrations.services.payment_organizations import PAYMENT_REPORT_COMPANY_CODES


class Command(BaseCommand):
    help = "按群配置推送到期付款日报/周报/月报；群配置中的公司可多选"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="仅显示到期任务，不生成回执、不发送")
        parser.add_argument("--company", help="仅检查指定组织代码")

    def handle(self, **options):
        now = timezone.localtime()
        today = now.date()
        groups = DingtalkGroupConfig.objects.filter(
            is_active=True,
            app__is_active=True,
        ).filter(
            Q(companies__is_active=True) | Q(companies__isnull=True, company__is_active=True)
        ).select_related("app", "company").prefetch_related("companies").distinct()
        if options.get("company"):
            groups = groups.filter(
                Q(companies__code=options["company"]) | Q(companies__isnull=True, company__code=options["company"])
            ).distinct()

        failures = 0
        for group in groups:
            if group.send_at > now.time():
                continue

            companies = list(
                group.companies.filter(
                    is_active=True, code__in=PAYMENT_REPORT_COMPANY_CODES
                )
            )
            if not group.companies.exists() and group.company_id and group.company.is_active and group.company.code in PAYMENT_REPORT_COMPANY_CODES:
                companies = [group.company]
            if options.get("company"):
                companies = [company for company in companies if company.code == options["company"]]

            for period in group.payment_report_types:
                if period not in ("day", "week", "month"):
                    raise CommandError(f"群配置 {group.pk} 的付款周期无效：{period}")
                if period == "week" and today.weekday() != 0:
                    continue
                if period == "month" and today.day != 1:
                    continue

                for company in companies:
                    if (
                        group.app.company_id != company.pk
                        and not group.app.company_mappings.filter(company=company).exists()
                    ):
                        raise CommandError(
                            f"群配置 {group.pk} 的公司 {company.code} 尚未映射到钉钉应用"
                        )
                    if options["dry_run"]:
                        self.stdout.write(
                            f"[dry-run] {company.code} / {group.name} / {period} / {today}"
                        )
                        continue

                    dispatch, created = PaymentReportDispatch.objects.get_or_create(
                        group=group,
                        company=company,
                        report_type=period,
                        delivery_date=today,
                    )
                    if not created:
                        continue
                    try:
                        call_command(
                            "send_payment_report",
                            period,
                            company=company.code,
                            app_id=group.app_id,
                            group_id=group.open_conversation_id,
                            base_date=today.isoformat(),
                            stdout=self.stdout,
                        )
                    except Exception as exc:
                        dispatch.status = "FAILED"
                        dispatch.error = str(exc)
                        failures += 1
                        self.stderr.write(str(exc))
                    else:
                        dispatch.status = "SENT"
                    dispatch.save(update_fields=["status", "error", "updated_at"])

        if failures:
            raise CommandError(
                f"{failures} 个付款推送失败；为避免卡片成功但附件失败时重复发送，请核对回执后手动补发"
            )
