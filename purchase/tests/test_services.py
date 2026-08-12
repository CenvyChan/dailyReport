from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from core.models import ExchangeRate, OperationLog, PurchaseAssignment, Supplier
from purchase.services import create_purchase_receipt


class PurchaseReceiptServiceTests(TestCase):
    def test_domestic_purchase_uses_cny_without_foreign_rate(self):
        user = User.objects.create_user("buyer-a")
        supplier = Supplier.objects.create(name="供应商 A")
        PurchaseAssignment.objects.create(user=user, supplier=supplier)
        receipt = create_purchase_receipt(
            actor=user,
            data={
                "supplier": supplier,
                "purchase_type": "DOMESTIC",
                "purchase_date": date(2026, 8, 10),
                "quantity": 5,
                "original_amount": "88.00",
            },
        )
        self.assertEqual(receipt.currency, "CNY")
        self.assertEqual(receipt.amount_cny, Decimal("88.00"))

    def test_foreign_purchase_uses_usd_rate_snapshot(self):
        user = User.objects.create_user("buyer-a")
        supplier = Supplier.objects.create(name="供应商 A")
        PurchaseAssignment.objects.create(user=user, supplier=supplier)
        ExchangeRate.objects.create(month=date(2026, 8, 1), usd_to_cny="6.8067")
        receipt = create_purchase_receipt(
            actor=user,
            data={
                "supplier": supplier,
                "purchase_type": "FOREIGN",
                "purchase_date": date(2026, 8, 10),
                "quantity": 5,
                "original_amount": "100.00",
            },
        )
        self.assertEqual(receipt.currency, "USD")
        self.assertEqual(receipt.amount_cny, Decimal("680.67"))

    def test_history_import_is_recorded_as_import(self):
        admin = User.objects.create_superuser("admin", password="pw")
        user = User.objects.create_user("buyer-a")
        supplier = Supplier.objects.create(name="供应商 A")
        PurchaseAssignment.objects.create(user=user, supplier=supplier)
        receipt = create_purchase_receipt(
            actor=admin,
            data={
                "supplier": supplier,
                "buyer": user,
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
