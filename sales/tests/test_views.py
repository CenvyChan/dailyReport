from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Customer, OperationLog, SalesAssignment
from core.services.companies import grant_company_access
from core.testing import company_a, company_b, login_with_company
from sales.models import SalesShipment


def make_shipment(company, customer, owner, **overrides):
    payload = {
        "company": company,
        "customer": customer,
        "owner": owner,
        "sale_type": "DOMESTIC",
        "shipment_date": "2026-08-10",
        "quantity": 1,
        "currency": "CNY",
        "original_amount": "10.00",
        "exchange_rate": "1.0000",
        "amount_cny": "10.00",
    }
    payload.update(overrides)
    return SalesShipment.objects.create(**payload)


class SalesViewTests(TestCase):
    def setUp(self):
        self.company = company_a()
        self.user = User.objects.create_user("sales-a")
        self.customer = Customer.objects.create(company=self.company, name="客户 A")
        SalesAssignment.objects.create(user=self.user, customer=self.customer)
        login_with_company(self.client, self.user, self.company)

    def test_unassigned_customer_is_rejected(self):
        unassigned = Customer.objects.create(company=self.company, name="未分配客户")
        response = self.client.post(
            reverse("sales:shipment_create"),
            {
                "customer": unassigned.pk,
                "sale_type": "DOMESTIC",
                "shipment_date": "2026-08-10",
                "quantity": 1,
                "original_amount": "10.00",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.headers["Content-Type"].startswith("text/html"))
        self.assertContains(response, "新增销售日报", status_code=400)
        self.assertContains(response, "请选择列表中的客户", status_code=400)

    def test_create_page_explains_customer_search_and_amount(self):
        response = self.client.get(reverse("sales:shipment_create"))

        self.assertContains(response, "可输入客户名称或销售业务员进行筛选")
        self.assertContains(response, "填写原币金额，无需自行换算人民币")

    def test_owner_can_edit_a_shipment_and_change_is_audited(self):
        shipment = make_shipment(self.company, self.customer, self.user)

        response = self.client.post(
            reverse("sales:shipment_edit", args=[shipment.pk]),
            {
                "customer": shipment.customer_id,
                "sale_type": "DOMESTIC",
                "shipment_date": "2026-08-11",
                "quantity": 2,
                "original_amount": "20.00",
            },
        )

        self.assertRedirects(response, reverse("sales:shipment_list"))
        shipment.refresh_from_db()
        self.assertEqual(str(shipment.amount_cny), "20.000000")
        audit = OperationLog.objects.get(action="UPDATE", object_id=str(shipment.pk))
        self.assertEqual(audit.before_data["quantity"], "1.000")
        self.assertEqual(audit.after_data["quantity"], "2.000")

    def test_owner_can_delete_a_shipment_and_change_is_audited(self):
        shipment = make_shipment(self.company, self.customer, self.user)

        response = self.client.post(reverse("sales:shipment_delete", args=[shipment.pk]))

        self.assertRedirects(response, reverse("sales:shipment_list"))
        self.assertFalse(SalesShipment.objects.filter(pk=shipment.pk).exists())
        audit = OperationLog.objects.get(action="DELETE", object_id=str(shipment.pk))
        self.assertEqual(audit.before_data["customer_id"], shipment.customer_id)
        self.assertEqual(audit.after_data, {})

    def test_another_salespersons_shipment_is_visible_but_not_editable(self):
        """可见范围放开到全公司后，别人的记录看得到但改不了。

        状态码从 404 变成 403 是有意的：记录确实存在、用户在列表里也看得到，
        说清楚「不该由你改」比装作不存在更好懂。
        """
        other_user = User.objects.create_user("sales-b")
        other_customer = Customer.objects.create(company=self.company, name="客户 B")
        SalesAssignment.objects.create(user=other_user, customer=other_customer)
        shipment = make_shipment(self.company, other_customer, other_user)

        listed = self.client.get(reverse("sales:shipment_list"))
        self.assertContains(listed, "客户 B")

        self.assertEqual(
            self.client.get(reverse("sales:shipment_edit", args=[shipment.pk])).status_code, 403
        )
        self.assertEqual(
            self.client.post(reverse("sales:shipment_delete", args=[shipment.pk])).status_code, 403
        )

    def test_list_hides_shipments_belonging_to_another_company(self):
        other_customer = Customer.objects.create(company=company_b(), name="客户 B 家")
        SalesAssignment.objects.create(user=self.user, customer=other_customer)
        make_shipment(company_b(), other_customer, self.user, original_amount="999.00", amount_cny="999.00")
        make_shipment(self.company, self.customer, self.user)

        response = self.client.get(reverse("sales:shipment_list"))

        self.assertContains(response, "客户 A")
        self.assertNotContains(response, "客户 B 家")

    def test_shipment_of_another_company_returns_404_even_for_its_owner(self):
        other_customer = Customer.objects.create(company=company_b(), name="客户 B 家")
        SalesAssignment.objects.create(user=self.user, customer=other_customer)
        shipment = make_shipment(company_b(), other_customer, self.user)

        response = self.client.get(reverse("sales:shipment_edit", args=[shipment.pk]))

        self.assertEqual(response.status_code, 404)

    def test_switching_company_changes_the_visible_rows(self):
        other = company_b()
        grant_company_access(self.user, [other])
        other_customer = Customer.objects.create(company=other, name="客户 B 家")
        SalesAssignment.objects.create(user=self.user, customer=other_customer)
        make_shipment(other, other_customer, self.user)
        make_shipment(self.company, self.customer, self.user)

        self.client.post(reverse("core:switch_company"), {"company": other.pk})
        response = self.client.get(reverse("sales:shipment_list"))

        self.assertContains(response, "客户 B 家")
        self.assertNotContains(response, "客户 A")

    def test_switching_to_an_unauthorised_company_is_rejected(self):
        response = self.client.post(reverse("core:switch_company"), {"company": company_b().pk})

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "没有该公司的访问权限", status_code=403)
