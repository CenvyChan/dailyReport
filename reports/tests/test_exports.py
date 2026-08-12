from datetime import date
from io import BytesIO

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from core.models import Customer, Supplier
from reports.exporters import sales_export_rows
from purchase.models import PurchaseReceipt
from sales.models import SalesShipment


class SalesExportTests(TestCase):
    def setUp(self):
        user = User.objects.create_user("sales-a")
        customer = Customer.objects.create(name="客户 A")
        SalesShipment.objects.create(
            customer=customer,
            owner=user,
            sale_type="DOMESTIC",
            shipment_date=date(2026, 8, 10),
            quantity=1,
            currency="CNY",
            original_amount="88.00",
            exchange_rate="1.0000",
            amount_cny="88.00",
        )

    def test_export_headers_include_original_and_converted_amounts(self):
        headers, rows = sales_export_rows(SalesShipment.objects.all())
        self.assertEqual(
            headers,
            ["出货日期", "客户", "负责人", "销售类型", "数量", "币种", "原币金额", "汇率快照", "折算人民币金额"],
        )
        self.assertEqual(len(rows), 1)

    def test_sales_export_applies_dashboard_filters(self):
        admin = User.objects.create_superuser("admin", password="pw")
        customer = Customer.objects.get(name="客户 A")
        SalesShipment.objects.create(
            customer=customer,
            owner=admin,
            sale_type="DOMESTIC",
            shipment_date=date(2026, 8, 11),
            quantity=2,
            currency="CNY",
            original_amount="99.00",
            exchange_rate="1.0000",
            amount_cny="99.00",
        )
        self.client.force_login(admin)

        response = self.client.get(reverse("reports:sales_export"), {"start": "2026-08-11"})

        workbook = load_workbook(BytesIO(response.content))
        self.assertEqual(workbook.active.max_row, 2)
        self.assertEqual(workbook.active.cell(row=2, column=1).value.date(), date(2026, 8, 11))

    def test_purchase_export_applies_dashboard_filters(self):
        admin = User.objects.create_superuser("admin", password="pw")
        supplier = Supplier.objects.create(name="供应商 A")
        for purchase_date, amount in ((date(2026, 8, 10), "88.00"), (date(2026, 8, 11), "99.00")):
            PurchaseReceipt.objects.create(
                supplier=supplier,
                buyer=admin,
                purchase_type="DOMESTIC",
                purchase_date=purchase_date,
                quantity=1,
                currency="CNY",
                original_amount=amount,
                exchange_rate="1.0000",
                amount_cny=amount,
            )
        self.client.force_login(admin)

        response = self.client.get(reverse("reports:purchase_export"), {"start": "2026-08-11"})

        workbook = load_workbook(BytesIO(response.content))
        self.assertEqual(workbook.active.max_row, 2)
        self.assertEqual(workbook.active.cell(row=2, column=1).value.date(), date(2026, 8, 11))
