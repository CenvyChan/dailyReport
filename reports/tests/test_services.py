from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from core.models import Customer
from reports.services import sales_dashboard
from sales.models import SalesShipment


class SalesDashboardTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", password="pw")
        customer = Customer.objects.create(name="客户 A")
        SalesShipment.objects.create(
            customer=customer,
            owner=self.admin,
            sale_type="DOMESTIC",
            shipment_date=date(2026, 8, 10),
            quantity=1,
            currency="CNY",
            original_amount="88.00",
            exchange_rate="1.0000",
            amount_cny="88.00",
        )
        SalesShipment.objects.create(
            customer=customer,
            owner=self.admin,
            sale_type="EXPORT",
            shipment_date=date(2026, 8, 10),
            quantity=1,
            currency="USD",
            original_amount="100.00",
            exchange_rate="6.8067",
            amount_cny="680.67",
        )

    def test_summary_keeps_cny_usd_and_converted_total_separate(self):
        dashboard = sales_dashboard(self.admin, {"start": "2026-08-01", "end": "2026-08-31"})
        self.assertEqual(dashboard["summary"]["cny_amount"], Decimal("88.00"))
        self.assertEqual(dashboard["summary"]["usd_amount"], Decimal("100.00"))
        self.assertEqual(dashboard["summary"]["amount_cny"], Decimal("768.67"))
