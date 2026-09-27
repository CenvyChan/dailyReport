from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from core.models import Customer
from core.testing import company_a
from integrations.models import BusinessType, StockTransaction
from integrations.services.kingdee_compare import monthly_reconciliation
from sales.models import SalesShipment


class ReconciliationTests(TestCase):
    def setUp(self):
        self.company = company_a()
        self.customer = Customer.objects.create(company=self.company, name="客户甲")
        self.user = User.objects.create_user("owner-a")
        SalesShipment.objects.create(
            company=self.company, customer=self.customer, owner=self.user, sale_type="DOMESTIC",
            shipment_date=date(2026, 9, 10), quantity=Decimal("5"), currency="CNY",
            original_amount=Decimal("500"), exchange_rate=Decimal("1"), amount_cny=Decimal("500"),
        )

    def _k3(self, fid, day, qty, amount, active=True):
        return StockTransaction.objects.create(
            company=self.company, business_type=BusinessType.SALES_OUT, form_id="SAL_OUTSTOCK",
            fid=fid, biz_date=day, total_quantity=Decimal(qty), total_amount=Decimal(amount), is_active=active,
        )

    def test_reconciliation_diff_on_same_day(self):
        self._k3("1", date(2026, 9, 10), "5", "480")
        report = monthly_reconciliation(company=self.company, year=2026, month=9, business_type=BusinessType.SALES_OUT)
        row = next(r for r in report["rows"] if r["date"] == date(2026, 9, 10))
        self.assertEqual(row["sys_amount"], Decimal("500"))
        self.assertEqual(row["k3_amount"], Decimal("480"))
        self.assertEqual(row["amount_diff"], Decimal("20"))
        self.assertEqual(report["totals"]["amount_diff"], Decimal("20"))

    def test_disabled_k3_excluded(self):
        self._k3("1", date(2026, 9, 10), "5", "480", active=False)
        report = monthly_reconciliation(company=self.company, year=2026, month=9, business_type=BusinessType.SALES_OUT)
        self.assertEqual(report["totals"]["k3_amount"], Decimal("0"))
        self.assertEqual(report["totals"]["k3_count"], 0)
