"""导入批量化：验证查询次数不随行数线性增长，且写入结果与逐行版本一致。

改批量前每行要跑 8-10 次查询（get_or_create ×4 + 汇率 + 归属校验 + INSERT +
每行一条 OperationLog），3000 行近 3 万次查询独占 SQLite 写锁。
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from core.models import Customer, ExchangeRate, OperationLog, SalesAssignment, Supplier
from core.testing import company_a
from purchase.importers import ImportPreview as PurchasePreview, commit_purchase_import
from purchase.models import PurchaseReceipt
from sales.importers import ImportPreview as SalesPreview, commit_sales_import
from sales.models import SalesShipment


def sales_rows(count, *, sale_type="DOMESTIC"):
    return [
        {
            "row_number": index + 2,
            "customer_name": f"客户{index % 7}",
            "owner_name": f"业务{index % 3}",
            "sale_type": sale_type,
            "shipment_date": date(2026, 8, (index % 28) + 1),
            "quantity": Decimal("2"),
            "original_amount": Decimal("100"),
        }
        for index in range(count)
    ]


def purchase_rows(count, *, purchase_type="DOMESTIC"):
    return [
        {
            "row_number": index + 2,
            "supplier_name": f"供应商{index % 7}",
            "buyer_name": f"采购{index % 3}",
            "purchase_type": purchase_type,
            "purchase_date": date(2026, 8, (index % 28) + 1),
            "quantity": Decimal("2"),
            "original_amount": Decimal("100"),
        }
        for index in range(count)
    ]


class SalesBulkImportTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", password="pw")
        self.company = company_a()

    def commit(self, rows, rates=()):
        preview = SalesPreview(len(rows), [], rows, rate_errors=[], exchange_rates=rates)
        return commit_sales_import(
            preview, actor=self.admin, company=self.company, source_file="t.xls"
        )

    def count_queries(self, action):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as captured:
            action()
        return len(captured)

    def test_query_count_does_not_grow_with_row_count(self):
        """10 行和 100 行的查询次数应该基本一致——这正是批量化的目的。"""
        small = self.count_queries(lambda: self.commit(sales_rows(10)))
        SalesShipment.objects.all().delete()
        large = self.count_queries(lambda: self.commit(sales_rows(100)))

        self.assertLess(large - small, 10, f"10 行用了 {small} 次查询，100 行用了 {large} 次")

    def test_all_rows_are_written_with_correct_amounts(self):
        self.assertEqual(self.commit(sales_rows(30)), 30)
        self.assertEqual(SalesShipment.objects.count(), 30)

        shipment = SalesShipment.objects.first()
        self.assertEqual(shipment.currency, "CNY")
        self.assertEqual(shipment.exchange_rate, Decimal("1"))
        self.assertEqual(shipment.amount_cny, Decimal("100"))
        self.assertEqual(shipment.source, "HISTORY_IMPORT")
        self.assertIsNotNone(shipment.import_batch)

    def test_export_rows_use_the_monthly_rate(self):
        rates = ({"month": date(2026, 8, 1), "usd_to_cny": Decimal("7.1")},)

        self.commit(sales_rows(5, sale_type="EXPORT"), rates=rates)

        shipment = SalesShipment.objects.first()
        self.assertEqual(shipment.currency, "USD")
        self.assertEqual(shipment.exchange_rate, Decimal("7.1"))
        self.assertEqual(shipment.amount_cny, Decimal("710.0"))

    def test_master_data_is_deduplicated_not_recreated(self):
        """7 个客户名重复出现在 30 行里，只应建 7 个客户。"""
        self.commit(sales_rows(30))

        self.assertEqual(Customer.objects.filter(company=self.company).count(), 7)
        self.assertEqual(User.objects.filter(username__startswith="业务").count(), 3)
        self.assertEqual(SalesAssignment.objects.count(), 21)

    def test_reimport_reuses_existing_master_data(self):
        self.commit(sales_rows(10))
        self.commit(sales_rows(10))

        self.assertEqual(Customer.objects.filter(company=self.company).count(), 7)
        self.assertEqual(SalesShipment.objects.count(), 20)

    def test_audit_records_one_entry_per_batch_not_per_row(self):
        """每行一条审计会让 3000 行的导入多出 3000 次 INSERT；明细可由
        import_batch 反查，所以只记批次级一条。"""
        OperationLog.objects.all().delete()

        self.commit(sales_rows(50))

        logs = OperationLog.objects.filter(action="IMPORT")
        self.assertEqual(logs.count(), 1)
        self.assertEqual(logs.first().after_data["row_count"], 50)

    def test_named_accounts_are_honoured(self):
        """源表写中文名、系统用拼音登录的场景。"""
        mapped = User.objects.create_user("yewu0")
        rows = sales_rows(3)
        preview = SalesPreview(len(rows), [], rows, rate_errors=[], exchange_rates=())

        commit_sales_import(
            preview,
            actor=self.admin,
            company=self.company,
            source_file="t.xls",
            people={"业务0": mapped},
        )

        self.assertTrue(SalesShipment.objects.filter(owner=mapped).exists())
        self.assertFalse(User.objects.filter(username="业务0").exists())

    def test_every_shipment_lands_in_the_current_company_with_an_assignment(self):
        """批量路径不再逐行调 _ensure_customer_assignment（那两项校验各是一次查询），
        改由构造方式保证：客户按当前公司取或建、归属在写日报前补齐。这里锁住不变量。"""
        self.commit(sales_rows(20))

        self.assertFalse(SalesShipment.objects.exclude(company=self.company).exists())
        self.assertFalse(
            SalesShipment.objects.exclude(customer__company=self.company).exists()
        )
        for shipment in SalesShipment.objects.select_related("customer", "owner"):
            self.assertTrue(
                SalesAssignment.objects.filter(
                    user=shipment.owner, customer=shipment.customer
                ).exists(),
                f"{shipment.owner} 缺少对 {shipment.customer} 的归属",
            )

    def test_a_customer_of_another_company_is_never_reused(self):
        """B 公司有同名客户时，不能把日报挂到那一条上。"""
        from core.testing import company_b

        other = Customer.objects.create(company=company_b(), name="客户0")

        self.commit(sales_rows(7))

        self.assertFalse(SalesShipment.objects.filter(customer=other).exists())
        self.assertTrue(
            Customer.objects.filter(company=self.company, name="客户0").exists()
        )


class PurchaseBulkImportTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", password="pw")
        self.company = company_a()

    def commit(self, rows):
        preview = PurchasePreview(len(rows), [], rows, rate_errors=[])
        return commit_purchase_import(
            preview, actor=self.admin, company=self.company, source_file="t.xls"
        )

    def test_all_rows_are_written_with_correct_amounts(self):
        self.assertEqual(self.commit(purchase_rows(30)), 30)
        self.assertEqual(PurchaseReceipt.objects.count(), 30)

        receipt = PurchaseReceipt.objects.first()
        self.assertEqual(receipt.currency, "CNY")
        self.assertEqual(receipt.amount_cny, Decimal("100"))

    def test_foreign_rows_use_the_monthly_rate(self):
        ExchangeRate.objects.create(
            company=self.company, month=date(2026, 8, 1), usd_to_cny=Decimal("7.2")
        )

        self.commit(purchase_rows(5, purchase_type="FOREIGN"))

        receipt = PurchaseReceipt.objects.first()
        self.assertEqual(receipt.currency, "USD")
        self.assertEqual(receipt.amount_cny, Decimal("720.0"))

    def test_missing_rate_aborts_the_whole_batch(self):
        """外币缺汇率时整批回滚，不能留下一半数据。"""
        from core.errors import MissingExchangeRate

        with self.assertRaises(MissingExchangeRate):
            self.commit(purchase_rows(5, purchase_type="FOREIGN"))

        self.assertEqual(PurchaseReceipt.objects.count(), 0)
        self.assertEqual(Supplier.objects.filter(company=self.company).count(), 0)

    def test_master_data_is_deduplicated(self):
        self.commit(purchase_rows(30))

        self.assertEqual(Supplier.objects.filter(company=self.company).count(), 7)
        self.assertEqual(User.objects.filter(username__startswith="采购").count(), 3)
