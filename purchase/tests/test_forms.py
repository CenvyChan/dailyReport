from django.contrib.auth.models import User
from django.test import TestCase

from core.models import PurchaseAssignment, Supplier
from core.testing import company_a, company_b
from purchase.forms import PurchaseReceiptForm


class PurchaseReceiptFormTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("buyer-a")

    def test_supplier_input_options_include_buyer_label(self):
        supplier = Supplier.objects.create(company=company_a(), name="供应商 A")
        PurchaseAssignment.objects.create(user=self.user, supplier=supplier)

        form = PurchaseReceiptForm(user=self.user, company=company_a())

        self.assertEqual(form.fields["supplier"].widget.attrs["list"], "purchase-supplier-options")
        self.assertIn("供应商 A（buyer-a）", form.supplier_options)

    def test_options_exclude_suppliers_belonging_to_another_company(self):
        PurchaseAssignment.objects.create(
            user=self.user, supplier=Supplier.objects.create(company=company_b(), name="供应商 B 家")
        )

        form = PurchaseReceiptForm(user=self.user, company=company_a())

        self.assertEqual(form.supplier_options, [])
