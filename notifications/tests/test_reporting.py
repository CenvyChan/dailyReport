from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from core.models import Customer, Supplier
from core.testing import company_a, company_b
from notifications.reporting import build_daily_report, has_any_data
from purchase.models import PurchaseReceipt
from sales.models import SalesShipment


def add_shipment(company, customer, owner, shipment_date, amount, **overrides):
    payload = {
        "company": company,
        "customer": customer,
        "owner": owner,
        "sale_type": "DOMESTIC",
        "shipment_date": shipment_date,
        "quantity": 1,
        "currency": "CNY",
        "original_amount": amount,
        "exchange_rate": "1.0000",
        "amount_cny": amount,
    }
    payload.update(overrides)
    return SalesShipment.objects.create(**payload)


class DailyReportTests(TestCase):
    def setUp(self):
        self.company = company_a()
        self.owner = User.objects.create_user("sales-a")
        self.customer = Customer.objects.create(company=self.company, name="客户 A")

    def test_today_month_and_year_totals_use_their_own_windows(self):
        add_shipment(self.company, self.customer, self.owner, date(2026, 8, 21), "100.00")
        add_shipment(self.company, self.customer, self.owner, date(2026, 8, 1), "50.00")
        add_shipment(self.company, self.customer, self.owner, date(2026, 3, 5), "20.00")
        add_shipment(self.company, self.customer, self.owner, date(2025, 12, 31), "999.00")

        report = build_daily_report(company=self.company, report_date=date(2026, 8, 21))

        self.assertEqual(report["sales"]["today"]["amount_cny"], Decimal("100.00"))
        self.assertEqual(report["sales"]["month"]["amount_cny"], Decimal("150.00"))
        self.assertEqual(report["sales"]["year"]["amount_cny"], Decimal("170.00"))

    def test_rows_of_another_company_are_never_included(self):
        other = company_b()
        other_customer = Customer.objects.create(company=other, name="客户 B 家")
        add_shipment(other, other_customer, self.owner, date(2026, 8, 21), "500.00")
        add_shipment(self.company, self.customer, self.owner, date(2026, 8, 21), "100.00")

        report = build_daily_report(company=self.company, report_date=date(2026, 8, 21))

        self.assertEqual(report["sales"]["today"]["count"], 1)
        self.assertEqual(report["sales"]["today"]["amount_cny"], Decimal("100.00"))
        self.assertEqual(len(report["sales"]["rows"]), 1)

    def test_original_currency_columns_stay_separate_from_converted_total(self):
        add_shipment(self.company, self.customer, self.owner, date(2026, 8, 21), "88.00")
        add_shipment(
            self.company,
            self.customer,
            self.owner,
            date(2026, 8, 21),
            "100.00",
            sale_type="EXPORT",
            currency="USD",
            exchange_rate="6.8067",
            amount_cny="680.67",
        )

        report = build_daily_report(company=self.company, report_date=date(2026, 8, 21))

        self.assertEqual(report["sales"]["today"]["cny_amount"], Decimal("88.00"))
        self.assertEqual(report["sales"]["today"]["usd_amount"], Decimal("100.00"))
        self.assertEqual(report["sales"]["today"]["amount_cny"], Decimal("768.67"))

    def test_scope_can_exclude_a_section_entirely(self):
        report = build_daily_report(
            company=self.company, report_date=date(2026, 8, 21), include_purchase=False
        )

        self.assertIsNotNone(report["sales"])
        self.assertIsNone(report["purchase"])

    def test_has_any_data_is_false_on_a_day_without_records(self):
        add_shipment(self.company, self.customer, self.owner, date(2026, 8, 20), "10.00")

        report = build_daily_report(company=self.company, report_date=date(2026, 8, 21))

        self.assertFalse(has_any_data(report))

    def test_has_any_data_is_true_when_only_purchase_has_rows(self):
        supplier = Supplier.objects.create(company=self.company, name="供应商 A")
        PurchaseReceipt.objects.create(
            company=self.company,
            supplier=supplier,
            buyer=self.owner,
            purchase_type="DOMESTIC",
            purchase_date=date(2026, 8, 21),
            quantity=1,
            currency="CNY",
            original_amount="30.00",
            exchange_rate="1.0000",
            amount_cny="30.00",
        )

        report = build_daily_report(company=self.company, report_date=date(2026, 8, 21))

        self.assertTrue(has_any_data(report))
        self.assertEqual(report["purchase"]["today"]["amount_cny"], Decimal("30.00"))
