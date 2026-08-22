from datetime import date, time
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import Customer
from core.testing import company_a, company_b
from notifications.models import DeliveryLog, MailingList
from sales.models import SalesShipment


REPORT_DATE = date(2026, 8, 21)


def seed_shipment(company, amount="100.00"):
    owner, _ = User.objects.get_or_create(username="sales-a")
    customer, _ = Customer.objects.get_or_create(company=company, name=f"客户 {company.code}")
    return SalesShipment.objects.create(
        company=company,
        customer=customer,
        owner=owner,
        sale_type="DOMESTIC",
        shipment_date=REPORT_DATE,
        quantity=1,
        currency="CNY",
        original_amount=amount,
        exchange_rate="1.0000",
        amount_cny=amount,
    )


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="report@example.com",
)
class SendDailyReportCommandTests(TestCase):
    def setUp(self):
        seed_shipment(company_a())
        seed_shipment(company_b(), amount="200.00")
        self.list_a = MailingList.objects.create(
            company=company_a(), name="A 日报", recipients="a@example.com", send_at=time(18, 0)
        )
        self.list_b = MailingList.objects.create(
            company=company_b(), name="B 日报", recipients="b@example.com", send_at=time(18, 0)
        )

    def _run(self, **options):
        output = StringIO()
        call_command("send_daily_report", date=REPORT_DATE.isoformat(), stdout=output, **options)
        return output.getvalue()

    def test_each_company_receives_only_its_own_email(self):
        self._run(now=True)

        self.assertEqual(len(mail.outbox), 2)
        by_recipient = {message.to[0]: message for message in mail.outbox}
        self.assertIn(company_a().name, by_recipient["a@example.com"].subject)
        self.assertIn("100.00", by_recipient["a@example.com"].body)
        self.assertNotIn("200.00", by_recipient["a@example.com"].body)
        self.assertIn("200.00", by_recipient["b@example.com"].body)

    def test_company_option_limits_the_run_to_one_company(self):
        self._run(now=True, company="A")

        self.assertEqual([message.to for message in mail.outbox], [["a@example.com"]])

    def test_unknown_company_code_is_rejected(self):
        with self.assertRaises(CommandError):
            self._run(now=True, company="ZZZ")

    def test_list_id_option_targets_a_single_mailing_list(self):
        self._run(now=True, list_id=self.list_b.pk)

        self.assertEqual([message.to for message in mail.outbox], [["b@example.com"]])

    def test_a_successful_day_is_not_sent_twice(self):
        self._run(now=True)
        mail.outbox.clear()

        self._run(now=True)

        self.assertEqual(mail.outbox, [])
        self.assertEqual(DeliveryLog.objects.filter(status=DeliveryLog.Status.SENT).count(), 2)

    def test_force_resends_a_day_that_already_went_out(self):
        self._run(now=True)
        mail.outbox.clear()

        self._run(force=True)

        self.assertEqual(len(mail.outbox), 2)

    def test_inactive_list_and_inactive_company_are_skipped(self):
        MailingList.objects.filter(pk=self.list_a.pk).update(is_active=False)
        company = company_b()
        company.is_active = False
        company.save(update_fields=["is_active"])

        output = self._run(now=True)

        self.assertEqual(mail.outbox, [])
        self.assertIn("没有到点或待发送", output)

    def test_dry_run_lists_targets_without_sending(self):
        output = self._run(now=True, dry_run=True)

        self.assertEqual(mail.outbox, [])
        self.assertEqual(DeliveryLog.objects.count(), 0)
        self.assertIn("a@example.com", output)

    def test_lists_are_held_back_until_their_send_time(self):
        with patch("django.utils.timezone.localtime") as localtime:
            localtime.return_value = timezone.datetime(2026, 8, 21, 9, 0)
            output = self._run()

        self.assertEqual(mail.outbox, [])
        self.assertIn("没有到点或待发送", output)

    def test_lists_go_out_once_their_send_time_has_passed(self):
        with patch("django.utils.timezone.localtime") as localtime:
            localtime.return_value = timezone.datetime(2026, 8, 21, 18, 5)
            self._run()

        self.assertEqual(len(mail.outbox), 2)

    def test_invalid_date_option_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command("send_daily_report", date="2026/08/21", stdout=StringIO())


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="report@example.com",
)
class RetryLimitTests(TestCase):
    """SMTP 故障时计划任务每 10 分钟重试一次就是一天 144 次，每次都要重建
    报表、重算工作簿，还各阻塞 EMAIL_TIMEOUT=30 秒。"""

    def setUp(self):
        seed_shipment(company_a())
        self.mailing_list = MailingList.objects.create(
            company=company_a(), name="A 日报", recipients="a@example.com", send_at=time(18, 0)
        )

    def _run(self, **options):
        output = StringIO()
        call_command("send_daily_report", date=REPORT_DATE.isoformat(), stdout=output, **options)
        return output.getvalue()

    def _log_failures(self, count):
        for _ in range(count):
            DeliveryLog.objects.create(
                mailing_list=self.mailing_list,
                report_date=REPORT_DATE,
                status=DeliveryLog.Status.FAILED,
                message="SMTP 拒绝连接",
            )

    def test_retries_stop_after_the_daily_attempt_limit(self):
        self._log_failures(5)

        output = self._run(now=True)

        self.assertIn("已放弃", output)
        self.assertIn("--force", output)
        self.assertEqual(len(mail.outbox), 0)

    def test_retrying_is_still_allowed_below_the_limit(self):
        self._log_failures(4)

        self._run(now=True)

        self.assertEqual(len(mail.outbox), 1)

    def test_force_overrides_the_limit_for_manual_resend(self):
        """修好 SMTP 后管理员要能手工补发。"""
        self._log_failures(10)

        self._run(force=True)

        self.assertEqual(len(mail.outbox), 1)

    def test_a_success_still_blocks_further_sends_regardless_of_failures(self):
        self._log_failures(2)
        DeliveryLog.objects.create(
            mailing_list=self.mailing_list,
            report_date=REPORT_DATE,
            status=DeliveryLog.Status.SENT,
        )

        self._run(now=True)

        self.assertEqual(len(mail.outbox), 0)

    def test_failures_on_another_day_do_not_block_today(self):
        for _ in range(9):
            DeliveryLog.objects.create(
                mailing_list=self.mailing_list,
                report_date=date(2026, 8, 20),
                status=DeliveryLog.Status.FAILED,
            )

        self._run(now=True)

        self.assertEqual(len(mail.outbox), 1)

    def test_failures_on_another_list_do_not_block_this_one(self):
        other = MailingList.objects.create(
            company=company_a(), name="另一组", recipients="c@example.com", send_at=time(18, 0)
        )
        for _ in range(9):
            DeliveryLog.objects.create(
                mailing_list=other, report_date=REPORT_DATE, status=DeliveryLog.Status.FAILED
            )

        self._run(now=True, list_id=self.mailing_list.pk)

        self.assertEqual(len(mail.outbox), 1)
