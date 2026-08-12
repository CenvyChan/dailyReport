from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from sales.importers import (
    ImportPreview,
    commit_sales_import,
    import_sales_history,
    validate_exchange_rate_rows,
    validate_sales_rows,
)


class SalesImportFlowTests(SimpleTestCase):
    @patch("sales.importers.commit_sales_import")
    @patch("sales.importers.preview_sales_import")
    def test_rate_errors_return_preview_without_commit(self, preview_import, commit_import):
        preview = ImportPreview(0, [], [], rate_errors=[{"row_number": 2}])
        preview_import.return_value = preview

        result = import_sales_history("history.xls", actor=object())

        self.assertIs(result, preview)
        commit_import.assert_not_called()


class SalesImportCommitTests(TestCase):
    def test_imported_owner_is_added_to_sales_group(self):
        admin = User.objects.create_superuser("admin")
        preview = ImportPreview(
            1,
            [],
            [
                {
                    "row_number": 2,
                    "customer_name": "Customer A",
                    "owner_name": "sales-owner",
                    "sale_type": "DOMESTIC",
                    "shipment_date": date(2026, 8, 10),
                    "quantity": 1,
                    "original_amount": Decimal("10"),
                }
            ],
            rate_errors=[],
            exchange_rates=(),
        )

        commit_sales_import(preview, actor=admin, source_file="history.xls")

        owner = User.objects.get(username="sales-owner")
        self.assertTrue(owner.groups.filter(name="sales").exists())


class SalesImporterTests(SimpleTestCase):
    def test_invalid_exchange_rate_row_is_reported_without_writing(self):
        errors, _ = validate_exchange_rate_rows([{"日期": "2026年8月", "汇率": "bad"}])

        self.assertEqual(errors[0]["field"], "汇率")

    def test_identical_business_rows_are_retained(self):
        rows = [
            {"客户名称": "客户 A", "业务跟单": "张三", "销售类型": "内销", "出货日期": "2026-08-10", "数量": 1, "金额": 10},
            {"客户名称": "客户 A", "业务跟单": "张三", "销售类型": "内销", "出货日期": "2026-08-10", "数量": 1, "金额": 10},
        ]
        preview = validate_sales_rows(rows)
        self.assertEqual(preview.valid_row_count, 2)
        self.assertEqual(preview.error_rows, [])

    def test_missing_customer_is_reported_with_source_row(self):
        preview = validate_sales_rows(
            [{"客户名称": "", "业务跟单": "张三", "销售类型": "内销", "出货日期": "2026-08-10", "数量": 1, "金额": 10}]
        )
        self.assertEqual(preview.error_rows[0]["row_number"], 2)
        self.assertEqual(preview.error_rows[0]["field"], "客户名称")

    def test_amount_with_excel_date_display_is_kept_as_serial_number(self):
        preview = validate_sales_rows(
            [{"客户名称": "客户 A", "业务跟单": "张三", "销售类型": "内销", "出货日期": "2025-08-11", "数量": 1, "金额": datetime(1983, 6, 2, 12, 0)}]
        )
        self.assertEqual(preview.valid_row_count, 1)
        self.assertEqual(preview.rows[0]["original_amount"], Decimal("30469.5"))

    def test_quantity_with_excel_date_display_is_kept_as_serial_number(self):
        preview = validate_sales_rows(
            [{"客户名称": "客户 A", "业务跟单": "张三", "销售类型": "外销", "出货日期": "2025-10-16", "数量": datetime(2286, 5, 15), "金额": 18720.18}]
        )
        self.assertEqual(preview.valid_row_count, 1)
        self.assertEqual(preview.rows[0]["quantity"], 141120)
