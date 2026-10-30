from datetime import date
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase

from core.models import (
    CompanyMembership,
    Customer,
    PurchaseAssignment,
    SalesAssignment,
    Supplier,
)
from core.testing import company_a
from purchase.models import PurchaseReceipt
from sales.models import SalesShipment


def shipment(company, owner, customer, amount="10"):
    return SalesShipment.objects.create(
        company=company,
        customer=customer,
        owner=owner,
        sale_type="DOMESTIC",
        shipment_date=date(2026, 10, 1),
        quantity=Decimal("1"),
        currency="CNY",
        original_amount=Decimal(amount),
        exchange_rate=Decimal("1"),
        amount_cny=Decimal(amount),
    )


def receipt(company, buyer, supplier):
    return PurchaseReceipt.objects.create(
        company=company,
        supplier=supplier,
        buyer=buyer,
        purchase_type="DOMESTIC",
        purchase_date=date(2026, 10, 1),
        quantity=Decimal("1"),
        currency="CNY",
        original_amount=Decimal("10"),
        exchange_rate=Decimal("1"),
        amount_cny=Decimal("10"),
    )


class MergeDuplicateUsersTests(TestCase):
    def setUp(self):
        self.company = company_a()
        self.sales_group, _ = Group.objects.get_or_create(name="sales")
        self.purchase_group, _ = Group.objects.get_or_create(name="purchase")

    def test_auto_matches_by_first_name_and_moves_all_references(self):
        target = User.objects.create_user("xuyingjia", first_name="许莹佳")
        source = User.objects.create(username="许莹佳")  # 导入误建的中文名账号
        customer = Customer.objects.create(company=self.company, name="客户甲")
        supplier = Supplier.objects.create(company=self.company, name="供应商甲")
        SalesAssignment.objects.create(user=source, customer=customer)
        PurchaseAssignment.objects.create(user=source, supplier=supplier)
        sales_row = shipment(self.company, source, customer)
        purchase_row = receipt(self.company, source, supplier)
        source.groups.add(self.sales_group, self.purchase_group)
        CompanyMembership.objects.create(user=source, company=self.company)

        call_command("merge_duplicate_users", apply=True, stdout=StringIO())

        sales_row.refresh_from_db()
        purchase_row.refresh_from_db()
        self.assertEqual(sales_row.owner, target)
        self.assertEqual(purchase_row.buyer, target)
        self.assertTrue(SalesAssignment.objects.filter(user=target, customer=customer).exists())
        self.assertTrue(PurchaseAssignment.objects.filter(user=target, supplier=supplier).exists())
        self.assertTrue(target.groups.filter(name="sales").exists())
        self.assertTrue(target.groups.filter(name="purchase").exists())
        self.assertTrue(CompanyMembership.objects.filter(user=target, company=self.company).exists())
        self.assertFalse(User.objects.filter(username="许莹佳").exists())

    def test_dry_run_does_not_write(self):
        User.objects.create_user("xuyingjia", first_name="许莹佳")
        source = User.objects.create(username="许莹佳")
        customer = Customer.objects.create(company=self.company, name="客户甲")
        row = shipment(self.company, source, customer)

        output = StringIO()
        call_command("merge_duplicate_users", stdout=output)

        row.refresh_from_db()
        self.assertEqual(row.owner, source)
        self.assertTrue(User.objects.filter(username="许莹佳").exists())
        self.assertIn("dry-run", output.getvalue())

    def test_explicit_map_can_merge_two_spellings_into_one_new_account(self):
        customer = Customer.objects.create(company=self.company, name="客户甲")
        teng = User.objects.create(username="腾琼")
        teng_correct = User.objects.create(username="滕琼")
        first_row = shipment(self.company, teng, customer)
        second_row = shipment(self.company, teng_correct, customer)

        call_command(
            "merge_duplicate_users",
            apply=True,
            map=["腾琼=tengqiong", "滕琼=tengqiong"],
            target_name=["tengqiong=滕琼"],
            create_missing=True,
            stdout=StringIO(),
        )

        target = User.objects.get(username="tengqiong")
        self.assertEqual(target.first_name, "滕琼")
        first_row.refresh_from_db()
        second_row.refresh_from_db()
        self.assertEqual(first_row.owner, target)
        self.assertEqual(second_row.owner, target)
        self.assertFalse(User.objects.filter(username__in=["腾琼", "滕琼"]).exists())

    def test_second_run_is_a_no_op(self):
        User.objects.create_user("xuyingjia", first_name="许莹佳")
        User.objects.create(username="许莹佳")
        call_command("merge_duplicate_users", apply=True, stdout=StringIO())

        output = StringIO()
        call_command("merge_duplicate_users", apply=True, stdout=output)

        self.assertIn("没有需要合并的账号", output.getvalue())

    def test_account_with_a_password_is_skipped_without_force(self):
        User.objects.create_user("xuyingjia", first_name="许莹佳")
        source = User.objects.create_user("许莹佳", password="a-real-password")

        output = StringIO()
        call_command("merge_duplicate_users", apply=True, stdout=output)

        self.assertTrue(User.objects.filter(pk=source.pk).exists())
        self.assertIn("已设置密码", output.getvalue())
