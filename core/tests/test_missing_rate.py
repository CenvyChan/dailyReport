from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.errors import MissingExchangeRate
from core.models import Customer, ExchangeRate, PurchaseAssignment, SalesAssignment, Supplier
from core.testing import company_a, company_b, login_with_company
from purchase.services import create_purchase_receipt
from sales.services import create_sales_shipment


class MissingExchangeRateTests(TestCase):
    """外币日报缺当月汇率时要给出可读提示，而不是 500。
    汇率按公司维护，所以另一家公司有汇率也不算有。"""

    def setUp(self):
        self.company = company_a()
        self.user = User.objects.create_user("sales-a")
        self.customer = Customer.objects.create(company=self.company, name="客户 A")
        SalesAssignment.objects.create(user=self.user, customer=self.customer)

    def test_service_raises_a_readable_error_naming_company_and_month(self):
        with self.assertRaises(MissingExchangeRate) as caught:
            create_sales_shipment(
                actor=self.user,
                company=self.company,
                data={
                    "customer": self.customer,
                    "sale_type": "EXPORT",
                    "shipment_date": date(2026, 8, 10),
                    "quantity": 1,
                    "original_amount": "100.00",
                },
            )

        message = str(caught.exception)
        self.assertIn(self.company.name, message)
        self.assertIn("2026年08月", message)

    def test_another_company_rate_does_not_satisfy_the_lookup(self):
        ExchangeRate.objects.create(company=company_b(), month=date(2026, 8, 1), usd_to_cny="7.2000")

        with self.assertRaises(MissingExchangeRate):
            create_sales_shipment(
                actor=self.user,
                company=self.company,
                data={
                    "customer": self.customer,
                    "sale_type": "EXPORT",
                    "shipment_date": date(2026, 8, 10),
                    "quantity": 1,
                    "original_amount": "100.00",
                },
            )

    def test_purchase_side_behaves_the_same(self):
        buyer = User.objects.create_user("buyer-a")
        supplier = Supplier.objects.create(company=self.company, name="供应商 A")
        PurchaseAssignment.objects.create(user=buyer, supplier=supplier)

        with self.assertRaises(MissingExchangeRate):
            create_purchase_receipt(
                actor=buyer,
                company=self.company,
                data={
                    "supplier": supplier,
                    "purchase_type": "FOREIGN",
                    "purchase_date": date(2026, 8, 10),
                    "quantity": 1,
                    "original_amount": "100.00",
                },
            )

    def test_sales_form_shows_the_error_instead_of_crashing(self):
        login_with_company(self.client, self.user, self.company)

        response = self.client.post(
            reverse("sales:shipment_create"),
            {
                "customer": f"{self.customer.name}（{self.user.username}）",
                "sale_type": "EXPORT",
                "shipment_date": "2026-08-10",
                "quantity": 1,
                "original_amount": "100.00",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "缺少", status_code=400)
        self.assertContains(response, "汇率", status_code=400)

    def test_purchase_form_shows_the_error_instead_of_crashing(self):
        buyer = User.objects.create_user("buyer-a")
        supplier = Supplier.objects.create(company=self.company, name="供应商 A")
        PurchaseAssignment.objects.create(user=buyer, supplier=supplier)
        login_with_company(self.client, buyer, self.company)

        response = self.client.post(
            reverse("purchase:receipt_create"),
            {
                "supplier": f"{supplier.name}（{buyer.username}）",
                "purchase_type": "FOREIGN",
                "purchase_date": "2026-08-10",
                "quantity": 1,
                "original_amount": "100.00",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "汇率", status_code=400)
