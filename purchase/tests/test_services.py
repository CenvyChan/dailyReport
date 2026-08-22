from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from core.errors import MissingExchangeRate
from core.models import ExchangeRate, OperationLog, PurchaseAssignment, Supplier
from core.testing import company_a, company_b
from purchase.services import create_purchase_receipt, purchase_queryset_for


class PurchaseReceiptServiceTests(TestCase):
    def setUp(self):
        self.company = company_a()
        self.user = User.objects.create_user("buyer-a")
        self.supplier = Supplier.objects.create(company=self.company, name="供应商 A")
        PurchaseAssignment.objects.create(user=self.user, supplier=self.supplier)

    def test_domestic_purchase_uses_cny_without_foreign_rate(self):
        receipt = create_purchase_receipt(
            actor=self.user,
            company=self.company,
            data={
                "supplier": self.supplier,
                "purchase_type": "DOMESTIC",
                "purchase_date": date(2026, 8, 10),
                "quantity": 5,
                "original_amount": "88.00",
            },
        )
        self.assertEqual(receipt.currency, "CNY")
        self.assertEqual(receipt.amount_cny, Decimal("88.00"))
        self.assertEqual(receipt.company, self.company)

    def test_foreign_purchase_uses_usd_rate_snapshot(self):
        ExchangeRate.objects.create(company=self.company, month=date(2026, 8, 1), usd_to_cny="6.8067")
        receipt = create_purchase_receipt(
            actor=self.user,
            company=self.company,
            data={
                "supplier": self.supplier,
                "purchase_type": "FOREIGN",
                "purchase_date": date(2026, 8, 10),
                "quantity": 5,
                "original_amount": "100.00",
            },
        )
        self.assertEqual(receipt.currency, "USD")
        self.assertEqual(receipt.amount_cny, Decimal("680.67"))

    def test_foreign_purchase_ignores_the_other_company_rate(self):
        ExchangeRate.objects.create(company=company_b(), month=date(2026, 8, 1), usd_to_cny="7.5000")

        with self.assertRaises(MissingExchangeRate):
            create_purchase_receipt(
                actor=self.user,
                company=self.company,
                data={
                    "supplier": self.supplier,
                    "purchase_type": "FOREIGN",
                    "purchase_date": date(2026, 8, 10),
                    "quantity": 1,
                    "original_amount": "100.00",
                },
            )

    def test_supplier_from_another_company_is_rejected(self):
        foreign_supplier = Supplier.objects.create(company=company_b(), name="供应商 B")
        PurchaseAssignment.objects.create(user=self.user, supplier=foreign_supplier)

        with self.assertRaises(PermissionError):
            create_purchase_receipt(
                actor=self.user,
                company=self.company,
                data={
                    "supplier": foreign_supplier,
                    "purchase_type": "DOMESTIC",
                    "purchase_date": date(2026, 8, 10),
                    "quantity": 1,
                    "original_amount": "10.00",
                },
            )

    def test_queryset_never_leaks_across_companies(self):
        create_purchase_receipt(
            actor=self.user,
            company=self.company,
            data={
                "supplier": self.supplier,
                "purchase_type": "DOMESTIC",
                "purchase_date": date(2026, 8, 10),
                "quantity": 1,
                "original_amount": "10.00",
            },
        )

        self.assertEqual(purchase_queryset_for(self.user, self.company).count(), 1)
        self.assertEqual(purchase_queryset_for(self.user, company_b()).count(), 0)
        self.assertEqual(purchase_queryset_for(self.user, None).count(), 0)

    def test_history_import_is_recorded_as_import(self):
        admin = User.objects.create_superuser("admin", password="pw")
        receipt = create_purchase_receipt(
            actor=admin,
            company=self.company,
            data={
                "supplier": self.supplier,
                "buyer": self.user,
                "purchase_type": "DOMESTIC",
                "purchase_date": date(2026, 8, 10),
                "quantity": 1,
                "original_amount": "10.00",
                "source": "HISTORY_IMPORT",
            },
        )

        self.assertTrue(
            OperationLog.objects.filter(action="IMPORT", object_id=str(receipt.pk)).exists()
        )
