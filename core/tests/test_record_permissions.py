"""记录级写权限。

新的权限模型：公司内可见范围完全放开（业务员要能核对同事的记录，report_viewer
更是必须看到全部），但增删改按绑定关系收紧——只有与该客户/供应商有绑定关系的
人才能维护对应的日报。

这里锁住的是「可见不可写」这个组合。此前写权限是靠视图层
get_object_or_404(queryset_for(...)) 取不到就 404 兜着的，放开可见范围后那道
守卫失效，服务层和视图层都补了显式校验。
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from core.models import Customer, PurchaseAssignment, SalesAssignment, Supplier
from core.services.permissions import (
    can_edit_customer,
    can_edit_supplier,
    editable_customer_ids,
    editable_supplier_ids,
    is_read_only,
)
from core.testing import company_a, company_b, login_with_company
from purchase.models import PurchaseReceipt
from purchase.services import delete_purchase_receipt, purchase_queryset_for
from sales.models import SalesShipment
from sales.services import delete_sales_shipment, sales_queryset_for


def make_shipment(company, customer, owner, *, day=10, amount="100.00"):
    return SalesShipment.objects.create(
        company=company,
        customer=customer,
        owner=owner,
        sale_type="DOMESTIC",
        shipment_date=date(2026, 8, day),
        quantity=1,
        currency="CNY",
        original_amount=Decimal(amount),
        exchange_rate=Decimal("1"),
        amount_cny=Decimal(amount),
    )


def make_receipt(company, supplier, buyer, *, day=10, amount="100.00"):
    return PurchaseReceipt.objects.create(
        company=company,
        supplier=supplier,
        buyer=buyer,
        purchase_type="DOMESTIC",
        purchase_date=date(2026, 8, day),
        quantity=1,
        currency="CNY",
        original_amount=Decimal(amount),
        exchange_rate=Decimal("1"),
        amount_cny=Decimal(amount),
    )


class SalesVisibilityTests(TestCase):
    def setUp(self):
        self.company = company_a()
        self.mine = User.objects.create_user("sales-a")
        self.mine.groups.add(Group.objects.get(name="sales"))
        self.theirs = User.objects.create_user("sales-b")
        self.theirs.groups.add(Group.objects.get(name="sales"))
        self.my_customer = Customer.objects.create(company=self.company, name="我的客户")
        self.their_customer = Customer.objects.create(company=self.company, name="同事的客户")
        SalesAssignment.objects.create(user=self.mine, customer=self.my_customer)
        SalesAssignment.objects.create(user=self.theirs, customer=self.their_customer)
        self.my_shipment = make_shipment(self.company, self.my_customer, self.mine)
        self.their_shipment = make_shipment(self.company, self.their_customer, self.theirs, day=11)

    def test_a_salesperson_sees_the_whole_company(self):
        """原先按 owner 过滤，只能看到自己录的。"""
        visible = sales_queryset_for(self.mine, self.company)

        self.assertEqual(visible.count(), 2)

    def test_company_isolation_still_holds(self):
        other_company = company_b()

        self.assertEqual(sales_queryset_for(self.mine, other_company).count(), 0)
        self.assertEqual(sales_queryset_for(self.mine, None).count(), 0)

    def test_editing_is_limited_to_bound_customers(self):
        self.assertTrue(can_edit_customer(self.mine, self.my_customer))
        self.assertFalse(can_edit_customer(self.mine, self.their_customer))

    def test_deleting_someone_elses_record_is_refused_at_the_service_layer(self):
        """视图层会先拦成 403，但服务层也必须自己拒——它此前是零校验的，
        任何拿到实例的调用方都能删。"""
        with self.assertRaises(PermissionError):
            delete_sales_shipment(actor=self.mine, shipment=self.their_shipment)

        self.assertTrue(SalesShipment.objects.filter(pk=self.their_shipment.pk).exists())

    def test_deleting_ones_own_record_still_works(self):
        delete_sales_shipment(actor=self.mine, shipment=self.my_shipment)

        self.assertFalse(SalesShipment.objects.filter(pk=self.my_shipment.pk).exists())

    def test_the_list_only_offers_buttons_for_editable_rows(self):
        login_with_company(self.client, self.mine, self.company)

        response = self.client.get(reverse("sales:shipment_list"))

        # 两条都看得见
        self.assertContains(response, "我的客户")
        self.assertContains(response, "同事的客户")
        # 但只有一个编辑入口
        self.assertContains(response, reverse("sales:shipment_edit", args=[self.my_shipment.pk]))
        self.assertNotContains(
            response, reverse("sales:shipment_edit", args=[self.their_shipment.pk])
        )

    def test_editable_ids_do_not_grow_with_the_number_of_rows(self):
        """关键性质是查询数恒定：逐行调 can_edit_customer 的话 50 行就是 50 次
        查询。这里加到 12 个客户，查询数不应变化。"""
        with self.assertNumQueries(4):
            editable_customer_ids(self.mine, self.company)

        for index in range(10):
            extra = Customer.objects.create(company=self.company, name=f"客户 {index}")
            SalesAssignment.objects.create(user=self.mine, customer=extra)

        with self.assertNumQueries(4):
            ids = editable_customer_ids(self.mine, self.company)

        self.assertEqual(len(ids), 11)


class PurchaseVisibilityTests(TestCase):
    """采购侧此前完全没有「不能编辑他人记录」的覆盖。"""

    def setUp(self):
        self.company = company_a()
        self.mine = User.objects.create_user("purchase-a")
        self.mine.groups.add(Group.objects.get(name="purchase"))
        self.theirs = User.objects.create_user("purchase-b")
        self.theirs.groups.add(Group.objects.get(name="purchase"))
        self.my_supplier = Supplier.objects.create(company=self.company, name="我的供应商")
        self.their_supplier = Supplier.objects.create(company=self.company, name="同事的供应商")
        PurchaseAssignment.objects.create(user=self.mine, supplier=self.my_supplier)
        PurchaseAssignment.objects.create(user=self.theirs, supplier=self.their_supplier)
        self.my_receipt = make_receipt(self.company, self.my_supplier, self.mine)
        self.their_receipt = make_receipt(self.company, self.their_supplier, self.theirs, day=11)
        login_with_company(self.client, self.mine, self.company)

    def test_a_buyer_sees_the_whole_company(self):
        self.assertEqual(purchase_queryset_for(self.mine, self.company).count(), 2)

    def test_editing_someone_elses_receipt_is_forbidden(self):
        response = self.client.get(reverse("purchase:receipt_edit", args=[self.their_receipt.pk]))

        self.assertEqual(response.status_code, 403)

    def test_deleting_someone_elses_receipt_is_forbidden(self):
        response = self.client.post(
            reverse("purchase:receipt_delete", args=[self.their_receipt.pk])
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(PurchaseReceipt.objects.filter(pk=self.their_receipt.pk).exists())

    def test_editing_ones_own_receipt_is_allowed(self):
        response = self.client.get(reverse("purchase:receipt_edit", args=[self.my_receipt.pk]))

        self.assertEqual(response.status_code, 200)

    def test_the_service_layer_refuses_too(self):
        with self.assertRaises(PermissionError):
            delete_purchase_receipt(actor=self.mine, receipt=self.their_receipt)

    def test_editable_supplier_ids_are_scoped_to_the_company(self):
        self.assertEqual(editable_supplier_ids(self.mine, self.company), {self.my_supplier.pk})
        self.assertEqual(editable_supplier_ids(self.mine, company_b()), set())


class ReadOnlyRoleTests(TestCase):
    """report_viewer 要能看两条业务线的全部日报，但完全不能增删改。

    此前它进销售/采购列表页得 403，报表页虽然放行、数据却是空的——
    sales_queryset_for 按 owner 过滤，而它不会是任何日报的 owner。
    """

    def setUp(self):
        self.company = company_a()
        self.viewer = User.objects.create_user("viewer")
        self.viewer.groups.add(Group.objects.get(name="report_viewer"))
        seller = User.objects.create_user("sales-a")
        customer = Customer.objects.create(company=self.company, name="某客户")
        SalesAssignment.objects.create(user=seller, customer=customer)
        self.shipment = make_shipment(self.company, customer, seller)
        supplier = Supplier.objects.create(company=self.company, name="某供应商")
        buyer = User.objects.create_user("purchase-a")
        PurchaseAssignment.objects.create(user=buyer, supplier=supplier)
        self.receipt = make_receipt(self.company, supplier, buyer)
        login_with_company(self.client, self.viewer, self.company)

    def test_it_is_recognised_as_read_only(self):
        self.assertTrue(is_read_only(self.viewer))

    def test_it_can_read_both_lists(self):
        self.assertEqual(self.client.get(reverse("sales:shipment_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("purchase:receipt_list")).status_code, 200)

    def test_the_data_is_actually_there_not_an_empty_page(self):
        response = self.client.get(reverse("sales:shipment_list"))

        self.assertContains(response, "某客户")

    def test_it_cannot_edit_or_delete(self):
        self.assertEqual(
            self.client.get(reverse("sales:shipment_edit", args=[self.shipment.pk])).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(reverse("sales:shipment_delete", args=[self.shipment.pk])).status_code,
            403,
        )

    def test_no_action_buttons_are_rendered_for_it(self):
        """只读用户看到点了才报错的按钮是最糟的体验。"""
        response = self.client.get(reverse("sales:shipment_list"))

        self.assertNotContains(response, 'class="edit"')
        self.assertNotContains(response, 'class="del"')

    def test_it_can_open_the_reports_and_the_comparison(self):
        self.assertEqual(self.client.get(reverse("reports:sales_dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("reports:monthly_comparison")).status_code, 200)

    def test_it_has_no_editable_ids_at_all(self):
        self.assertEqual(editable_customer_ids(self.viewer, self.company), set())
        self.assertEqual(editable_supplier_ids(self.viewer, self.company), set())

    def test_an_administrator_in_the_viewer_group_is_not_read_only(self):
        """管理员即使也挂了 report_viewer 也不该被限制。"""
        admin = User.objects.create_superuser("admin", password="pw")
        admin.groups.add(Group.objects.get(name="report_viewer"))

        self.assertFalse(is_read_only(admin))
        self.assertIsNone(editable_customer_ids(admin, self.company))


class CrossCompanyAssignmentTests(TestCase):
    """绑定关系表没有 company 字段，公司归属靠 customer.company 间接确定。
    不限定公司的话，A 公司的客户绑定会让这个人在 B 公司也拿到销售权限。"""

    def setUp(self):
        self.company_a = company_a()
        self.company_b = company_b()
        self.user = User.objects.create_user("only-in-a")
        customer = Customer.objects.create(company=self.company_a, name="A 公司的客户")
        SalesAssignment.objects.create(user=self.user, customer=customer)

    def test_an_assignment_in_one_company_does_not_grant_access_to_another(self):
        from core.services.permissions import can_access_sales

        self.assertTrue(can_access_sales(self.user, self.company_a))
        self.assertFalse(can_access_sales(self.user, self.company_b))

    def test_editable_ids_are_empty_in_the_other_company(self):
        self.assertEqual(editable_customer_ids(self.user, self.company_b), set())
