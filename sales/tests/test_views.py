from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Customer, OperationLog, SalesAssignment
from sales.models import SalesShipment


class SalesViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("sales-a")
        assigned = Customer.objects.create(name="客户 A")
        SalesAssignment.objects.create(user=self.user, customer=assigned)

    def test_unassigned_customer_is_rejected(self):
        self.client.force_login(self.user)
        unassigned = Customer.objects.create(name="未分配客户")
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
        self.client.force_login(self.user)

        response = self.client.get(reverse("sales:shipment_create"))

        self.assertContains(response, "可输入客户名称或销售业务员进行筛选")
        self.assertContains(response, "填写原币金额，无需自行换算人民币")

    def test_owner_can_edit_a_shipment_and_change_is_audited(self):
        shipment = SalesShipment.objects.create(
            customer=Customer.objects.get(name="客户 A"),
            owner=self.user,
            sale_type="DOMESTIC",
            shipment_date="2026-08-10",
            quantity=1,
            currency="CNY",
            original_amount="10.00",
            exchange_rate="1.0000",
            amount_cny="10.00",
        )
        self.client.force_login(self.user)

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
        self.assertEqual(audit.before_data["quantity"], 1)
        self.assertEqual(audit.after_data["quantity"], 2)

    def test_owner_can_delete_a_shipment_and_change_is_audited(self):
        shipment = SalesShipment.objects.create(
            customer=Customer.objects.get(name="客户 A"),
            owner=self.user,
            sale_type="DOMESTIC",
            shipment_date="2026-08-10",
            quantity=1,
            currency="CNY",
            original_amount="10.00",
            exchange_rate="1.0000",
            amount_cny="10.00",
        )
        self.client.force_login(self.user)

        response = self.client.post(reverse("sales:shipment_delete", args=[shipment.pk]))

        self.assertRedirects(response, reverse("sales:shipment_list"))
        self.assertFalse(SalesShipment.objects.filter(pk=shipment.pk).exists())
        audit = OperationLog.objects.get(action="DELETE", object_id=str(shipment.pk))
        self.assertEqual(audit.before_data["customer_id"], shipment.customer_id)
        self.assertEqual(audit.after_data, {})

    def test_owner_cannot_edit_another_salesperson_shipment(self):
        other_user = User.objects.create_user("sales-b")
        other_customer = Customer.objects.create(name="客户 B")
        SalesAssignment.objects.create(user=other_user, customer=other_customer)
        shipment = SalesShipment.objects.create(
            customer=other_customer,
            owner=other_user,
            sale_type="DOMESTIC",
            shipment_date="2026-08-10",
            quantity=1,
            currency="CNY",
            original_amount="10.00",
            exchange_rate="1.0000",
            amount_cny="10.00",
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("sales:shipment_edit", args=[shipment.pk]))

        self.assertEqual(response.status_code, 404)
