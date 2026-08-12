from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from purchase.importers import (
    ImportPreview,
    commit_purchase_import,
    validate_purchase_rates,
    validate_purchase_rows,
)


class PurchaseImportCommitTests(TestCase):
    def test_imported_buyer_is_added_to_purchase_group(self):
        admin = User.objects.create_superuser("admin")
        preview = ImportPreview(
            1,
            [],
            [
                {
                    "row_number": 2,
                    "supplier_name": "Supplier A",
                    "buyer_name": "purchase-buyer",
                    "purchase_type": "DOMESTIC",
                    "purchase_date": date(2026, 8, 10),
                    "quantity": 1,
                    "original_amount": Decimal("10"),
                }
            ],
            rate_errors=[],
        )

        commit_purchase_import(preview, actor=admin, source_file="history.xls")

        buyer = User.objects.get(username="purchase-buyer")
        self.assertTrue(buyer.groups.filter(name="purchase").exists())


class PurchaseImporterTests(SimpleTestCase):
    def test_foreign_purchase_without_month_rate_is_reported(self):
        errors = validate_purchase_rates(
            [{"row_number": 2, "purchase_type": "FOREIGN", "purchase_date": __import__("datetime").date(2026, 8, 10)}],
            available_months=set(),
        )

        self.assertEqual(errors[0]["field"], "汇率")

    def test_missing_supplier_is_reported_with_source_row(self):
        preview = validate_purchase_rows(
            [{"供应商": "", "采购员": "李四", "采购类型": "国内采购", "采购日期": "2026-08-10", "数量": 1, "金额": 10}]
        )
        self.assertEqual(preview.error_rows[0]["row_number"], 2)
        self.assertEqual(preview.error_rows[0]["field"], "供应商")

    def test_identical_rows_are_retained(self):
        row = {"供应商": "供应商 A", "采购员": "李四", "采购类型": "国外采购", "采购日期": "2026-08-10", "数量": 1, "金额": 10}
        preview = validate_purchase_rows([row, row.copy()])
        self.assertEqual(preview.valid_row_count, 2)

    def test_sales_style_columns_are_accepted_for_purchase_source(self):
        preview = validate_purchase_rows(
            [{"客户名称": "采购供应商 A", "业务跟单": "李四", "销售类型": "外销", "出货日期": "2026-08-10", "数量": 1, "金额": 10}]
        )
        self.assertEqual(preview.valid_row_count, 1)
        self.assertEqual(preview.rows[0]["supplier_name"], "采购供应商 A")
