"""日报负责人必须由所选客户/供应商的归属关系带出，不能默认成当前操作人。
这是线上真实报过的 bug：管理员代录时报「客户未分配给销售负责人」。"""

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from core.models import Customer, PurchaseAssignment, SalesAssignment, Supplier
from core.testing import company_a, login_with_company
from purchase.models import PurchaseReceipt
from sales.models import SalesShipment


class SalesOwnerResolutionTests(TestCase):
    def setUp(self):
        self.company = company_a()
        self.admin = User.objects.create_superuser("admin", password="pw")
        self.seller = User.objects.create_user("zhangsan", first_name="张三")
        self.seller.groups.add(Group.objects.get(name="sales"))
        self.customer = Customer.objects.create(company=self.company, name="示例客户甲")
        SalesAssignment.objects.create(user=self.seller, customer=self.customer)

    def test_option_labels_show_the_real_name_not_the_username(self):
        login_with_company(self.client, self.admin, self.company)

        response = self.client.get(reverse("sales:shipment_create"))

        self.assertContains(response, "示例客户甲（张三）")
        self.assertNotContains(response, "示例客户甲（zhangsan）")

    def test_administrator_recording_for_someone_else_succeeds(self):
        """线上报错场景：管理员选别人负责的客户录入，不应再被拒。"""
        login_with_company(self.client, self.admin, self.company)

        response = self.client.post(
            reverse("sales:shipment_create"),
            {
                "customer": "示例客户甲（张三）",
                "sale_type": "DOMESTIC",
                "shipment_date": "2026-08-31",
                "quantity": "34",
                "original_amount": "5213",
            },
        )

        self.assertRedirects(response, reverse("sales:shipment_list"))
        shipment = SalesShipment.objects.get()
        self.assertEqual(shipment.owner, self.seller)

    def test_owner_comes_from_the_customer_not_the_operator(self):
        login_with_company(self.client, self.admin, self.company)

        self.client.post(
            reverse("sales:shipment_create"),
            {
                "customer": "示例客户甲（张三）",
                "sale_type": "DOMESTIC",
                "shipment_date": "2026-08-31",
                "quantity": "1",
                "original_amount": "10",
            },
        )

        self.assertNotEqual(SalesShipment.objects.get().owner, self.admin)

    def test_a_customer_shared_by_two_sellers_offers_both_options(self):
        other = User.objects.create_user("lisi", first_name="李四")
        SalesAssignment.objects.create(user=other, customer=self.customer)
        login_with_company(self.client, self.admin, self.company)

        response = self.client.get(reverse("sales:shipment_create"))

        self.assertContains(response, "示例客户甲（张三）")
        self.assertContains(response, "示例客户甲（李四）")

    def test_choosing_the_other_seller_label_assigns_that_seller(self):
        other = User.objects.create_user("lisi", first_name="李四")
        SalesAssignment.objects.create(user=other, customer=self.customer)
        login_with_company(self.client, self.admin, self.company)

        self.client.post(
            reverse("sales:shipment_create"),
            {
                "customer": "示例客户甲（李四）",
                "sale_type": "DOMESTIC",
                "shipment_date": "2026-08-31",
                "quantity": "1",
                "original_amount": "10",
            },
        )

        self.assertEqual(SalesShipment.objects.get().owner, other)

    def test_unassigned_customer_is_reported_clearly(self):
        Customer.objects.create(company=self.company, name="孤儿客户")
        login_with_company(self.client, self.admin, self.company)

        response = self.client.post(
            reverse("sales:shipment_create"),
            {
                "customer": "孤儿客户（未分配）",
                "sale_type": "DOMESTIC",
                "shipment_date": "2026-08-31",
                "quantity": "1",
                "original_amount": "10",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "还没有分配销售负责人", status_code=400)

    def test_seller_recording_for_own_customer_still_works(self):
        login_with_company(self.client, self.seller, self.company)

        response = self.client.post(
            reverse("sales:shipment_create"),
            {
                "customer": "示例客户甲（张三）",
                "sale_type": "DOMESTIC",
                "shipment_date": "2026-08-31",
                "quantity": "1",
                "original_amount": "10",
            },
        )

        self.assertRedirects(response, reverse("sales:shipment_list"))
        self.assertEqual(SalesShipment.objects.get().owner, self.seller)

    def test_list_shows_the_real_name(self):
        SalesShipment.objects.create(
            company=self.company, customer=self.customer, owner=self.seller,
            sale_type="DOMESTIC", shipment_date="2026-08-31", quantity="1",
            currency="CNY", original_amount="10", exchange_rate="1", amount_cny="10",
        )
        login_with_company(self.client, self.admin, self.company)

        response = self.client.get(reverse("sales:shipment_list"), {"preset": "all"})

        self.assertContains(response, "张三")


class PurchaseOwnerResolutionTests(TestCase):
    def setUp(self):
        self.company = company_a()
        self.admin = User.objects.create_superuser("admin", password="pw")
        self.buyer = User.objects.create_user("wangwu", first_name="王五")
        self.buyer.groups.add(Group.objects.get(name="purchase"))
        self.supplier = Supplier.objects.create(company=self.company, name="某供应商")
        PurchaseAssignment.objects.create(user=self.buyer, supplier=self.supplier)

    def test_option_labels_show_the_real_name(self):
        login_with_company(self.client, self.admin, self.company)

        response = self.client.get(reverse("purchase:receipt_create"))

        self.assertContains(response, "某供应商（王五）")
        self.assertNotContains(response, "某供应商（wangwu）")

    def test_administrator_recording_for_someone_else_succeeds(self):
        login_with_company(self.client, self.admin, self.company)

        response = self.client.post(
            reverse("purchase:receipt_create"),
            {
                "supplier": "某供应商（王五）",
                "purchase_type": "DOMESTIC",
                "purchase_date": "2026-08-31",
                "quantity": "5",
                "original_amount": "100",
            },
        )

        self.assertRedirects(response, reverse("purchase:receipt_list"))
        self.assertEqual(PurchaseReceipt.objects.get().buyer, self.buyer)

    def test_unassigned_supplier_is_reported_clearly(self):
        Supplier.objects.create(company=self.company, name="孤儿供应商")
        login_with_company(self.client, self.admin, self.company)

        response = self.client.post(
            reverse("purchase:receipt_create"),
            {
                "supplier": "孤儿供应商（未分配）",
                "purchase_type": "DOMESTIC",
                "purchase_date": "2026-08-31",
                "quantity": "1",
                "original_amount": "10",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "还没有分配采购负责人", status_code=400)
