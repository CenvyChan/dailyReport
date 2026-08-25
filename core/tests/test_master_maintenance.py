"""客户/供应商的查询与维护开放给业务角色：销售管客户，采购管供应商。"""

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from core.models import (
    Customer,
    OperationLog,
    PurchaseAssignment,
    SalesAssignment,
    Supplier,
)
from core.testing import company_a, company_b, login_with_company


class CustomerMaintenanceTests(TestCase):
    def setUp(self):
        self.company = company_a()
        self.seller = User.objects.create_user("seller", first_name="销售甲")
        self.seller.groups.add(Group.objects.get(name="sales"))
        login_with_company(self.client, self.seller, self.company)

    def _my_customer(self, name, **kwargs):
        """造一个绑给当前业务员的客户。

        绑定关系是可见与可写的唯一依据：不绑的话业务员看不到也改不了。
        """
        customer = Customer.objects.create(company=self.company, name=name, **kwargs)
        SalesAssignment.objects.create(user=self.seller, customer=customer)
        return customer

    def test_sales_role_can_open_the_customer_list(self):
        self._my_customer("客户甲")

        response = self.client.get(reverse("core:customer_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "客户甲")

    def test_the_list_hides_customers_belonging_to_other_salespeople(self):
        """与「新增日报时只能选到自己绑定的客户」保持一致。此前列表页的起点是
        model.objects.filter(company=...)，任何 sales 组成员能看到并编辑本公司
        全部客户，两处口径自相矛盾。"""
        self._my_customer("我的客户")
        Customer.objects.create(company=self.company, name="别人的客户")

        response = self.client.get(reverse("core:customer_list"))

        self.assertContains(response, "我的客户")
        self.assertNotContains(response, "别人的客户")

    def test_editing_an_unassigned_customer_is_forbidden(self):
        other = Customer.objects.create(company=self.company, name="别人的客户")

        response = self.client.get(reverse("core:customer_edit", args=[other.pk]))

        self.assertEqual(response.status_code, 403)

    def test_sales_role_can_create_a_customer_with_audit(self):
        response = self.client.post(reverse("core:customer_create"), {"name": "新客户", "is_active": "on"})

        self.assertRedirects(response, reverse("core:customer_list"))
        customer = Customer.objects.get(company=self.company, name="新客户")
        self.assertTrue(OperationLog.objects.filter(action="CREATE", object_id=str(customer.pk)).exists())

    def test_sales_role_can_edit_a_customer(self):
        customer = self._my_customer("旧名")

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
        self._my_customer("本公司客户")
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
        self._my_customer("上海某某")
        self._my_customer("北京某某")

        response = self.client.get(reverse("core:customer_list"), {"q": "上海"})

        self.assertContains(response, "上海某某")
        self.assertNotContains(response, "北京某某")

    def test_status_filter_separates_active_and_inactive(self):
        self._my_customer("在用的", is_active=True)
        self._my_customer("停掉的", is_active=False)

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

    def _my_supplier(self, name, **kwargs):
        supplier = Supplier.objects.create(company=self.company, name=name, **kwargs)
        PurchaseAssignment.objects.create(user=self.buyer, supplier=supplier)
        return supplier

    def test_purchase_role_can_create_a_supplier(self):
        response = self.client.post(reverse("core:supplier_create"), {"name": "新供应商", "is_active": "on"})

        self.assertRedirects(response, reverse("core:supplier_list"))
        self.assertTrue(Supplier.objects.filter(company=self.company, name="新供应商").exists())

    def test_purchase_role_can_open_and_search_the_supplier_list(self):
        self._my_supplier("甲供应商")
        self._my_supplier("乙供应商")

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


class OwnerBindingTests(TestCase):
    """客户/供应商的负责人绑定。

    绑定关系此前只能在 Django admin 里加：前台新建的客户永远是「未分配」，
    创建者自己都选不到它去录日报。现在表单上有「负责业务员」字段，
    业务员自己新建时默认把自己勾上。
    """

    def setUp(self):
        self.company = company_a()
        self.seller = User.objects.create_user("seller", first_name="销售甲")
        self.seller.groups.add(Group.objects.get(name="sales"))
        self.colleague = User.objects.create_user("mate", first_name="销售乙")
        self.colleague.groups.add(Group.objects.get(name="sales"))
        login_with_company(self.client, self.colleague, self.company)
        login_with_company(self.client, self.seller, self.company)

    def test_creating_a_customer_binds_it_to_the_creator(self):
        """否则建完立刻就看不见也改不了——绑定关系是可见和可写的唯一依据。"""
        self.client.post(reverse("core:customer_create"), {"name": "我建的", "is_active": "on"})

        customer = Customer.objects.get(company=self.company, name="我建的")
        self.assertTrue(SalesAssignment.objects.filter(user=self.seller, customer=customer).exists())

    def test_the_creator_can_see_and_edit_it_right_away(self):
        self.client.post(reverse("core:customer_create"), {"name": "我建的", "is_active": "on"})
        customer = Customer.objects.get(company=self.company, name="我建的")

        self.assertContains(self.client.get(reverse("core:customer_list")), "我建的")
        self.assertEqual(
            self.client.get(reverse("core:customer_edit", args=[customer.pk])).status_code, 200
        )

    def test_the_form_offers_an_owner_field(self):
        response = self.client.get(reverse("core:customer_create"))

        self.assertContains(response, "负责业务员")
        self.assertContains(response, "销售乙")

    def test_a_salesperson_can_add_a_colleague_as_a_co_owner(self):
        customer = Customer.objects.create(company=self.company, name="共管客户")
        SalesAssignment.objects.create(user=self.seller, customer=customer)

        self.client.post(
            reverse("core:customer_edit", args=[customer.pk]),
            {"name": "共管客户", "is_active": "on", "owners": [self.seller.pk, self.colleague.pk]},
        )

        owners = set(
            SalesAssignment.objects.filter(customer=customer).values_list("user_id", flat=True)
        )
        self.assertEqual(owners, {self.seller.pk, self.colleague.pk})

    def test_a_salesperson_cannot_drop_themselves(self):
        """转走之后自己就看不见也改不了了，等于绕过「只有负责人能改」去动别人的数据。"""
        customer = Customer.objects.create(company=self.company, name="我的客户")
        SalesAssignment.objects.create(user=self.seller, customer=customer)

        response = self.client.post(
            reverse("core:customer_edit", args=[customer.pk]),
            {"name": "我的客户", "is_active": "on", "owners": [self.colleague.pk]},
        )

        self.assertContains(response, "不能把自己从负责人里去掉", status_code=200)
        self.assertTrue(SalesAssignment.objects.filter(user=self.seller, customer=customer).exists())

    def test_an_administrator_can_reassign_freely(self):
        customer = Customer.objects.create(company=self.company, name="待转交")
        SalesAssignment.objects.create(user=self.seller, customer=customer)
        admin = User.objects.create_superuser("admin", password="pw")
        login_with_company(self.client, admin, self.company)

        self.client.post(
            reverse("core:customer_edit", args=[customer.pk]),
            {"name": "待转交", "is_active": "on", "owners": [self.colleague.pk]},
        )

        owners = set(
            SalesAssignment.objects.filter(customer=customer).values_list("user_id", flat=True)
        )
        self.assertEqual(owners, {self.colleague.pk})

    def test_existing_owners_are_preselected_when_editing(self):
        customer = Customer.objects.create(company=self.company, name="我的客户")
        SalesAssignment.objects.create(user=self.seller, customer=customer)

        response = self.client.get(reverse("core:customer_edit", args=[customer.pk]))

        self.assertEqual(list(response.context["form"].initial["owners"]), [self.seller.pk])

    def test_the_service_layer_refuses_to_edit_an_unbound_customer(self):
        from core.services.master_data import save_customer

        other = Customer.objects.create(company=self.company, name="别人的客户")

        with self.assertRaises(PermissionError):
            save_customer(
                actor=self.seller,
                company=self.company,
                data={"name": "改名", "is_active": True},
                instance=other,
            )


class OwnerPickerUiTests(TestCase):
    """负责业务员选择器的呈现。

    字段必须保持多选：线上有 33 个客户绑定了 2 个业务员（历史导入带来的），
    改成单选会在保存时静默删掉一个绑定，那个业务员从此看不到自己的客户。
    做法是保留多选能力，但让常见情况（只有一个负责人）看起来和单选一样清爽。
    """

    def setUp(self):
        from core.models import CompanyMembership

        self.company = company_a()
        self.seller = User.objects.create_user("seller", first_name="销售甲")
        self.seller.groups.add(Group.objects.get(name="sales"))
        for index in range(9):
            mate = User.objects.create_user(f"mate{index}", first_name=f"销售{index}")
            mate.groups.add(Group.objects.get(name="sales"))
            CompanyMembership.objects.create(user=mate, company=self.company)
        login_with_company(self.client, self.seller, self.company)

    def test_the_owner_field_comes_before_the_active_toggle(self):
        """负责人比启用状态重要。owners 是声明式字段，默认会排到 Meta.fields
        之后，靠 field_order 提上来。"""
        body = self.client.get(reverse("core:customer_create")).content.decode()

        self.assertLess(body.index('for="id_owners'), body.index('for="id_is_active"'))

    def test_the_choice_group_gets_its_own_class(self):
        """.form-card .field input{width:100%} 会把勾选框撑成整行宽，方块被推到
        右端和姓名错开老远——看起来像布局坏了。多选组要走单独的样式。"""
        response = self.client.get(reverse("core:customer_create"))

        self.assertContains(response, "field-choices")

    def test_a_single_checkbox_gets_the_toggle_class(self):
        response = self.client.get(reverse("core:customer_create"))

        self.assertContains(response, "field-toggle")

    def test_the_picker_script_is_loaded(self):
        response = self.client.get(reverse("core:customer_create"))

        self.assertContains(response, "owner-picker.js")

    def test_all_company_salespeople_are_offered(self):
        body = self.client.get(reverse("core:customer_create")).content.decode()

        self.assertEqual(body.count('name="owners"'), 10)

    def test_the_field_stays_multi_select(self):
        """回归保护：线上已有客户绑定两个业务员，改成单选会丢绑定。"""
        from core.forms import CustomerForm

        form = CustomerForm(company=self.company, actor=self.seller)

        self.assertTrue(form.fields["owners"].widget.allow_multiple_selected)

    def test_two_owners_can_be_saved_and_read_back(self):
        customer = Customer.objects.create(company=self.company, name="共管")
        SalesAssignment.objects.create(user=self.seller, customer=customer)
        mate = User.objects.get(username="mate0")

        self.client.post(
            reverse("core:customer_edit", args=[customer.pk]),
            {"name": "共管", "is_active": "on", "owners": [self.seller.pk, mate.pk]},
        )

        self.assertEqual(SalesAssignment.objects.filter(customer=customer).count(), 2)
