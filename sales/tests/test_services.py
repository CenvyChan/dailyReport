from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from core.models import Customer, ExchangeRate, OperationLog, SalesAssignment
from sales.services import create_sales_shipment


class SalesShipmentServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("sales-a")
        self.customer = Customer.objects.create(name="客户 A")
        SalesAssignment.objects.create(user=self.user, customer=self.customer)
        ExchangeRate.objects.create(month=date(2026, 8, 1), usd_to_cny="6.8067")

    def test_export_sale_uses_usd_and_month_rate_snapshot(self):
        shipment = create_sales_shipment(
            actor=self.user,
            data={
                "customer": self.customer,
                "sale_type": "EXPORT",
                "shipment_date": date(2026, 8, 10),
                "quantity": 20,
                "original_amount": "100.00",
            },
        )
        self.assertEqual(shipment.currency, "USD")
        self.assertEqual(shipment.exchange_rate, Decimal("6.8067"))
        self.assertEqual(shipment.amount_cny, Decimal("680.67"))

    def test_administrator_can_import_for_assigned_owner(self):
        admin = User.objects.create_superuser("admin", password="pw")
        shipment = create_sales_shipment(
            actor=admin,
            data={
                "customer": self.customer,
                "owner": self.user,
                "sale_type": "DOMESTIC",
                "shipment_date": date(2026, 8, 10),
                "quantity": 1,
                "original_amount": "10.00",
                "source": "HISTORY_IMPORT",
            },
        )
        self.assertEqual(shipment.owner, self.user)

    def test_history_import_is_recorded_as_import(self):
        admin = User.objects.create_superuser("admin", password="pw")
        shipment = create_sales_shipment(
            actor=admin,
            data={
                "customer": self.customer,
                "owner": self.user,
                "sale_type": "DOMESTIC",
                "shipment_date": date(2026, 8, 10),
                "quantity": 1,
                "original_amount": "10.00",
                "source": "HISTORY_IMPORT",
            },
        )

        self.assertTrue(
            OperationLog.objects.filter(action="IMPORT", object_id=str(shipment.pk)).exists()
        )
