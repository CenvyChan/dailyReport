from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Customer
from core.testing import company_a, login_with_company
from sales.models import SalesShipment


class ReportFilterValidationTests(TestCase):
    """手改 URL 传非法筛选值不应该把页面打成 500。"""

    def setUp(self):
        self.admin = User.objects.create_superuser("admin", password="pw")
        customer = Customer.objects.create(company=company_a(), name="客户 A")
        SalesShipment.objects.create(
            company=company_a(),
            customer=customer,
            owner=self.admin,
            sale_type="DOMESTIC",
            shipment_date=date(2026, 8, 10),
            quantity=1,
            currency="CNY",
            original_amount="10.00",
            exchange_rate="1.0000",
            amount_cny="10.00",
        )
        login_with_company(self.client, self.admin, company_a())

    def test_non_numeric_ids_and_bad_dates_are_ignored(self):
        for query in (
            {"person_id": "abc"},
            {"counterpart_id": "xyz"},
            {"start": "notadate"},
            {"end": "13-13-13"},
            {"start": "2026-99-99"},
        ):
            with self.subTest(query=query):
                self.assertEqual(self.client.get(reverse("reports:sales_dashboard"), query).status_code, 200)
                self.assertEqual(self.client.get(reverse("reports:purchase_dashboard"), query).status_code, 200)

    def test_bad_filters_do_not_silently_drop_valid_rows(self):
        response = self.client.get(reverse("reports:sales_dashboard"), {"start": "notadate"})

        self.assertEqual(response.context["dashboard"]["summary"]["quantity"], 1)

    def test_valid_date_filter_still_applies(self):
        response = self.client.get(reverse("reports:sales_export"), {"start": "2026-08-11"})

        self.assertEqual(response.status_code, 200)
