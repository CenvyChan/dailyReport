from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase

from core.errors import UnresolvedImportPeople
from core.services.users import describe_import_people
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

    def test_chinese_name_matches_existing_account_by_first_name(self):
        """回归：系统里是 xuyingjia/first_name=许莹佳，源表写许莹佳时必须复用，
        不能另建一个中文名账号。2026-10-30 的重复账号事故就是这条没做到。"""
        zhangsan = User.objects.create_user("zhangsan", first_name="张三")

        commit_sales_import(
            sales_preview(), actor=self.admin, company=self.company, source_file="t.xls"
        )

        self.assertEqual(SalesShipment.objects.get().owner, zhangsan)
        self.assertFalse(User.objects.filter(username="张三").exists())

    def test_unknown_name_is_rejected_instead_of_creating_an_account(self):
        with self.assertRaises(UnresolvedImportPeople):
            commit_sales_import(
                sales_preview(), actor=self.admin, company=self.company, source_file="t.xls"
            )

        self.assertFalse(User.objects.filter(username="张三").exists())
        self.assertEqual(SalesShipment.objects.count(), 0)

    def test_a_name_missing_from_the_mapping_is_rejected(self):
        with self.assertRaises(UnresolvedImportPeople):
            commit_sales_import(
                sales_preview(),
                actor=self.admin,
                company=self.company,
                source_file="t.xls",
                people={"王五": User.objects.create_user("wangwu")},
            )

        self.assertFalse(User.objects.filter(username="张三").exists())

    def test_create_missing_still_available_when_explicitly_requested(self):
        """页面勾选「为未匹配姓名建号」后才允许创建，且必须写入 first_name，
        否则下次导入仍然匹配不上。"""
        commit_sales_import(
            sales_preview(),
            actor=self.admin,
            company=self.company,
            source_file="t.xls",
            create_missing=True,
        )

        created = User.objects.get(username="张三")
        self.assertEqual(created.first_name, "张三")
        self.assertEqual(SalesShipment.objects.get().owner, created)

    def test_ambiguous_name_is_rejected(self):
        User.objects.create_user("zhangsan1", first_name="张三")
        User.objects.create_user("zhangsan2", first_name="张三")

        with self.assertRaises(UnresolvedImportPeople) as raised:
            commit_sales_import(
                sales_preview(), actor=self.admin, company=self.company, source_file="t.xls"
            )

        self.assertIn("张三", str(raised.exception))
        self.assertEqual(SalesShipment.objects.count(), 0)

    def test_preview_describes_matched_and_unmatched_names(self):
        User.objects.create_user("zhangsan", first_name="张三")

        info = describe_import_people(["张三", "李四"])

        self.assertEqual(info["matched"][0]["username"], "zhangsan")
        self.assertEqual(info["unmatched"], ["李四"])
        self.assertEqual(info["ambiguous"], [])

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
