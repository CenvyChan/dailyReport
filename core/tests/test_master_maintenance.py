"""客户/供应商的查询与维护开放给业务角色：销售管客户，采购管供应商。"""

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from core.models import Customer, OperationLog, Supplier
from core.testing import company_a, company_b, login_with_company


class CustomerMaintenanceTests(TestCase):
    def setUp(self):
        self.company = company_a()
        self.seller = User.objects.create_user("seller", first_name="销售甲")
        self.seller.groups.add(Group.objects.get(name="sales"))
        login_with_company(self.client, self.seller, self.company)

    def test_sales_role_can_open_the_customer_list(self):
        Customer.objects.create(company=self.company, name="客户甲")

        response = self.client.get(reverse("core:customer_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "客户甲")

    def test_sales_role_can_create_a_customer_with_audit(self):
        response = self.client.post(reverse("core:customer_create"), {"name": "新客户", "is_active": "on"})

        self.assertRedirects(response, reverse("core:customer_list"))
        customer = Customer.objects.get(company=self.company, name="新客户")
        self.assertTrue(OperationLog.objects.filter(action="CREATE", object_id=str(customer.pk)).exists())

    def test_sales_role_can_edit_a_customer(self):
        customer = Customer.objects.create(company=self.company, name="旧名")

        response = self.client.post(
            reverse("core:customer_edit", args=[customer.pk]), {"name": "新名", "is_active": "on"}
        )

        self.assertRedirects(response, reverse("core:customer_list"))
        customer.refresh_from_db()
        self.assertEqual(customer.name, "新名")

    def test_customer_is_created_in_the_active_company_only(self):
        self.client.post(reverse("core:customer_create"), {"name": "只在A", "is_active": "on"})

        self.assertTrue(Customer.objects.filter(company=self.company, name="只在A").exists())
        self.assertFalse(Customer.objects.filter(company=company_b(), name="只在A").exists())

    def test_duplicate_name_in_the_same_company_is_rejected(self):
        Customer.objects.create(company=self.company, name="重名")

        response = self.client.post(reverse("core:customer_create"), {"name": "重名", "is_active": "on"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "该名称在本公司已存在")

    def test_the_same_name_is_allowed_in_the_other_company(self):
        Customer.objects.create(company=company_b(), name="同名")

        response = self.client.post(reverse("core:customer_create"), {"name": "同名", "is_active": "on"})

        self.assertRedirects(response, reverse("core:customer_list"))

    def test_list_only_shows_the_active_company(self):
        Customer.objects.create(company=self.company, name="本公司客户")
        Customer.objects.create(company=company_b(), name="他公司客户")

        response = self.client.get(reverse("core:customer_list"))

        self.assertContains(response, "本公司客户")
        self.assertNotContains(response, "他公司客户")

    def test_customer_of_another_company_cannot_be_edited(self):
        other = Customer.objects.create(company=company_b(), name="他公司客户")

        self.assertEqual(
            self.client.get(reverse("core:customer_edit", args=[other.pk])).status_code, 404
        )

    def test_search_filters_by_name(self):
        Customer.objects.create(company=self.company, name="上海某某")
        Customer.objects.create(company=self.company, name="北京某某")

        response = self.client.get(reverse("core:customer_list"), {"q": "上海"})

        self.assertContains(response, "上海某某")
        self.assertNotContains(response, "北京某某")

    def test_status_filter_separates_active_and_inactive(self):
        Customer.objects.create(company=self.company, name="在用的", is_active=True)
        Customer.objects.create(company=self.company, name="停掉的", is_active=False)

        response = self.client.get(reverse("core:customer_list"), {"status": "inactive"})

        self.assertContains(response, "停掉的")
        self.assertNotContains(response, "在用的")

    def test_purchase_only_role_cannot_touch_customers(self):
        buyer = User.objects.create_user("buyer")
        buyer.groups.add(Group.objects.get(name="purchase"))
        login_with_company(self.client, buyer, self.company)

        self.assertEqual(self.client.get(reverse("core:customer_list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("core:customer_create")).status_code, 403)


class SupplierMaintenanceTests(TestCase):
    def setUp(self):
        self.company = company_a()
        self.buyer = User.objects.create_user("buyer", first_name="采购甲")
        self.buyer.groups.add(Group.objects.get(name="purchase"))
        login_with_company(self.client, self.buyer, self.company)

    def test_purchase_role_can_create_a_supplier(self):
        response = self.client.post(reverse("core:supplier_create"), {"name": "新供应商", "is_active": "on"})

        self.assertRedirects(response, reverse("core:supplier_list"))
        self.assertTrue(Supplier.objects.filter(company=self.company, name="新供应商").exists())

    def test_purchase_role_can_open_and_search_the_supplier_list(self):
        Supplier.objects.create(company=self.company, name="甲供应商")
        Supplier.objects.create(company=self.company, name="乙供应商")

        response = self.client.get(reverse("core:supplier_list"), {"q": "甲"})

        self.assertContains(response, "甲供应商")
        self.assertNotContains(response, "乙供应商")

    def test_sales_only_role_cannot_touch_suppliers(self):
        seller = User.objects.create_user("seller")
        seller.groups.add(Group.objects.get(name="sales"))
        login_with_company(self.client, seller, self.company)

        self.assertEqual(self.client.get(reverse("core:supplier_list")).status_code, 403)

    def test_administrator_can_maintain_both(self):
        admin = User.objects.create_superuser("admin", password="pw")
        login_with_company(self.client, admin, self.company)

        self.assertEqual(self.client.get(reverse("core:customer_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("core:supplier_list")).status_code, 200)
