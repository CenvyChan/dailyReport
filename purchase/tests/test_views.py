from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import resolve, reverse

from core.models import OperationLog, PurchaseAssignment, Supplier
from core.testing import company_a, company_b, login_with_company
from purchase.models import PurchaseReceipt


def make_receipt(company, supplier, buyer, **overrides):
    payload = {
        "company": company,
        "supplier": supplier,
        "buyer": buyer,
        "purchase_type": "DOMESTIC",
        "purchase_date": "2026-08-10",
        "quantity": 1,
        "currency": "CNY",
        "original_amount": "10.00",
        "exchange_rate": "1.0000",
        "amount_cny": "10.00",
    }
    payload.update(overrides)
    return PurchaseReceipt.objects.create(**payload)


class PurchaseRouteTests(TestCase):
    def setUp(self):
        self.company = company_a()
        self.user = User.objects.create_user("buyer-a")
        self.supplier = Supplier.objects.create(company=self.company, name="供应商 A")
        PurchaseAssignment.objects.create(user=self.user, supplier=self.supplier)
        login_with_company(self.client, self.user, self.company)

    def test_purchase_api_resolves_to_purchase_namespace(self):
        match = resolve("/api/purchase/receipts/")
        self.assertEqual(match.namespace, "purchase_api")

    def test_invalid_supplier_is_rendered_as_chinese_form_error(self):
        response = self.client.post(
            reverse("purchase:receipt_create"),
            {
                "supplier": "未分配供应商",
                "purchase_type": "DOMESTIC",
                "purchase_date": "2026-08-10",
                "quantity": 1,
                "original_amount": "10.00",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.headers["Content-Type"].startswith("text/html"))
        self.assertContains(response, "新增采购日报", status_code=400)
        self.assertContains(response, "请选择列表中的供应商", status_code=400)

    def test_create_page_explains_supplier_search_and_amount(self):
        response = self.client.get(reverse("purchase:receipt_create"))

        self.assertContains(response, "可输入供应商名称或采购员进行筛选")
        self.assertContains(response, "填写原币金额，无需自行换算人民币")

    def test_buyer_can_edit_a_receipt_and_change_is_audited(self):
        receipt = make_receipt(self.company, self.supplier, self.user)

        response = self.client.post(
            reverse("purchase:receipt_edit", args=[receipt.pk]),
            {
                "supplier": self.supplier.pk,
                "purchase_type": "DOMESTIC",
                "purchase_date": "2026-08-11",
                "quantity": 2,
                "original_amount": "20.00",
            },
        )

        self.assertRedirects(response, reverse("purchase:receipt_list"))
        receipt.refresh_from_db()
        self.assertEqual(str(receipt.amount_cny), "20.000000")
        audit = OperationLog.objects.get(action="UPDATE", object_id=str(receipt.pk))
        self.assertEqual(audit.before_data["quantity"], "1.000")
        self.assertEqual(audit.after_data["quantity"], "2.000")

    def test_buyer_can_delete_a_receipt_and_change_is_audited(self):
        receipt = make_receipt(self.company, self.supplier, self.user)

        response = self.client.post(reverse("purchase:receipt_delete", args=[receipt.pk]))

        self.assertRedirects(response, reverse("purchase:receipt_list"))
        self.assertFalse(PurchaseReceipt.objects.filter(pk=receipt.pk).exists())
        audit = OperationLog.objects.get(action="DELETE", object_id=str(receipt.pk))
        self.assertEqual(audit.before_data["supplier_id"], self.supplier.pk)
        self.assertEqual(audit.after_data, {})

    def test_list_hides_receipts_belonging_to_another_company(self):
        other_supplier = Supplier.objects.create(company=company_b(), name="供应商 B 家")
        PurchaseAssignment.objects.create(user=self.user, supplier=other_supplier)
        make_receipt(company_b(), other_supplier, self.user)
        make_receipt(self.company, self.supplier, self.user)

        response = self.client.get(reverse("purchase:receipt_list"))

        self.assertContains(response, "供应商 A")
        self.assertNotContains(response, "供应商 B 家")

    def test_receipt_of_another_company_returns_404_even_for_its_buyer(self):
        other_supplier = Supplier.objects.create(company=company_b(), name="供应商 B 家")
        PurchaseAssignment.objects.create(user=self.user, supplier=other_supplier)
        receipt = make_receipt(company_b(), other_supplier, self.user)

        response = self.client.get(reverse("purchase:receipt_edit", args=[receipt.pk]))

        self.assertEqual(response.status_code, 404)
