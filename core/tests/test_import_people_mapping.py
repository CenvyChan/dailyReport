from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase

from core.testing import company_a
from purchase.importers import ImportPreview as PurchasePreview, commit_purchase_import
from purchase.models import PurchaseReceipt
from sales.importers import ImportPreview as SalesPreview, commit_sales_import
from sales.models import SalesShipment


def sales_preview():
    return SalesPreview(
        1,
        [],
        [
            {
                "row_number": 2,
                "customer_name": "客户甲",
                "owner_name": "张三",
                "sale_type": "DOMESTIC",
                "shipment_date": date(2026, 8, 10),
                "quantity": Decimal("1"),
                "original_amount": Decimal("10"),
            }
        ],
        rate_errors=[],
        exchange_rates=(),
    )


def purchase_preview():
    return PurchasePreview(
        1,
        [],
        [
            {
                "row_number": 2,
                "supplier_name": "供应商甲",
                "buyer_name": "李四",
                "purchase_type": "DOMESTIC",
                "purchase_date": date(2026, 8, 10),
                "quantity": Decimal("1"),
                "original_amount": Decimal("10"),
            }
        ],
        rate_errors=[],
    )


class ImportPeopleMappingTests(TestCase):
    """源表里写的是中文姓名，但系统里用拼音/工号登录。
    导入时必须能把日报挂到指定账号上，而不是另建一个中文名账号。"""

    def setUp(self):
        self.admin = User.objects.create_superuser("admin", password="pw")
        self.company = company_a()

    def test_sales_rows_are_owned_by_the_mapped_account(self):
        zhangsan = User.objects.create_user("zhangsan", first_name="张三")

        commit_sales_import(
            sales_preview(),
            actor=self.admin,
            company=self.company,
            source_file="t.xls",
            people={"张三": zhangsan},
        )

        self.assertEqual(SalesShipment.objects.get().owner, zhangsan)
        self.assertFalse(User.objects.filter(username="张三").exists())
        self.assertTrue(zhangsan.groups.filter(name="sales").exists())

    def test_purchase_rows_are_owned_by_the_mapped_account(self):
        lisi = User.objects.create_user("lisi", first_name="李四")

        commit_purchase_import(
            purchase_preview(),
            actor=self.admin,
            company=self.company,
            source_file="t.xls",
            people={"李四": lisi},
        )

        self.assertEqual(PurchaseReceipt.objects.get().buyer, lisi)
        self.assertFalse(User.objects.filter(username="李四").exists())
        self.assertTrue(lisi.groups.filter(name="purchase").exists())

    def test_without_a_mapping_the_chinese_name_becomes_the_username(self):
        """页面导入不传映射，保持原有行为（按姓名自动建号）。"""
        commit_sales_import(
            sales_preview(), actor=self.admin, company=self.company, source_file="t.xls"
        )

        self.assertTrue(User.objects.filter(username="张三").exists())
        self.assertEqual(SalesShipment.objects.get().owner.username, "张三")

    def test_a_name_missing_from_the_mapping_falls_back_to_auto_creation(self):
        commit_sales_import(
            sales_preview(),
            actor=self.admin,
            company=self.company,
            source_file="t.xls",
            people={"王五": User.objects.create_user("wangwu")},
        )

        self.assertEqual(SalesShipment.objects.get().owner.username, "张三")

    def test_mapped_account_keeps_its_existing_roles(self):
        both = User.objects.create_user("both")
        both.groups.add(Group.objects.get(name="purchase"))

        commit_sales_import(
            sales_preview(),
            actor=self.admin,
            company=self.company,
            source_file="t.xls",
            people={"张三": both},
        )

        self.assertEqual(sorted(both.groups.values_list("name", flat=True)), ["purchase", "sales"])
