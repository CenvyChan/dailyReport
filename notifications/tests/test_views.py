from datetime import time

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import Customer, OperationLog
from core.testing import company_a, company_b, login_with_company
from notifications.models import DeliveryLog, MailingList
from sales.models import SalesShipment


class MailingListViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", password="pw")
        login_with_company(self.client, self.admin, company_a())

    def test_administrator_can_create_a_mailing_list_for_the_active_company(self):
        response = self.client.post(
            reverse("notifications:mailing_list_create"),
            {
                "name": "管理层日报",
                "scope": MailingList.Scope.BOTH,
                "recipients": "boss@example.com",
                "cc_recipients": "",
                "send_at": "18:00",
                "attach_workbook": "on",
                "is_active": "on",
            },
        )

        self.assertRedirects(response, reverse("notifications:mailing_list_index"))
        mailing_list = MailingList.objects.get()
        self.assertEqual(mailing_list.company, company_a())
        self.assertEqual(mailing_list.recipient_list(), ["boss@example.com"])
        self.assertTrue(
            OperationLog.objects.filter(
                action="CREATE", model_label="notifications.MailingList", object_id=str(mailing_list.pk)
            ).exists()
        )

    def test_index_only_lists_the_active_company(self):
        MailingList.objects.create(company=company_a(), name="A 日报", recipients="a@example.com", send_at=time(18, 0))
        MailingList.objects.create(company=company_b(), name="B 日报", recipients="b@example.com", send_at=time(18, 0))

        response = self.client.get(reverse("notifications:mailing_list_index"))

        self.assertContains(response, "a@example.com")
        self.assertNotContains(response, "b@example.com")

    def test_mailing_list_of_another_company_cannot_be_edited(self):
        mailing_list = MailingList.objects.create(
            company=company_b(), name="B 日报", recipients="b@example.com", send_at=time(18, 0)
        )

        response = self.client.get(reverse("notifications:mailing_list_edit", args=[mailing_list.pk]))

        self.assertEqual(response.status_code, 404)

    def test_duplicate_name_inside_one_company_is_a_friendly_error(self):
        MailingList.objects.create(company=company_a(), name="管理层日报", recipients="a@example.com", send_at=time(18, 0))

        response = self.client.post(
            reverse("notifications:mailing_list_create"),
            {
                "name": "管理层日报",
                "scope": MailingList.Scope.BOTH,
                "recipients": "other@example.com",
                "cc_recipients": "",
                "send_at": "18:00",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "该公司下已存在同名收件组")

    def test_invalid_recipient_address_is_rejected(self):
        response = self.client.post(
            reverse("notifications:mailing_list_create"),
            {
                "name": "管理层日报",
                "scope": MailingList.Scope.BOTH,
                "recipients": "not-an-email",
                "cc_recipients": "",
                "send_at": "18:00",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "邮箱格式无效")
        self.assertEqual(MailingList.objects.count(), 0)

    def test_non_administrator_cannot_open_the_page(self):
        user = User.objects.create_user("sales-a")
        login_with_company(self.client, user, company_a())

        self.assertEqual(self.client.get(reverse("notifications:mailing_list_index")).status_code, 403)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="report@example.com",
)
class SendNowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", password="pw")
        login_with_company(self.client, self.admin, company_a())
        self.mailing_list = MailingList.objects.create(
            company=company_a(), name="管理层日报", recipients="boss@example.com", send_at=time(18, 0)
        )

    def test_send_now_delivers_today_report_even_when_empty(self):
        response = self.client.post(
            reverse("notifications:mailing_list_send_now", args=[self.mailing_list.pk])
        )

        self.assertRedirects(response, reverse("notifications:mailing_list_index"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(DeliveryLog.objects.get().status, DeliveryLog.Status.SENT)

    def test_send_now_includes_todays_rows(self):
        customer = Customer.objects.create(company=company_a(), name="客户 A")
        SalesShipment.objects.create(
            company=company_a(),
            customer=customer,
            owner=self.admin,
            sale_type="DOMESTIC",
            shipment_date=timezone.localdate(),
            quantity=1,
            currency="CNY",
            original_amount="66.00",
            exchange_rate="1.0000",
            amount_cny="66.00",
        )

        self.client.post(reverse("notifications:mailing_list_send_now", args=[self.mailing_list.pk]))

        self.assertIn("66.00", mail.outbox[0].body)

    def test_get_request_is_refused(self):
        response = self.client.get(
            reverse("notifications:mailing_list_send_now", args=[self.mailing_list.pk])
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(mail.outbox, [])

    def test_send_now_cannot_target_another_company_list(self):
        other = MailingList.objects.create(
            company=company_b(), name="B 日报", recipients="b@example.com", send_at=time(18, 0)
        )

        response = self.client.post(reverse("notifications:mailing_list_send_now", args=[other.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertEqual(mail.outbox, [])
