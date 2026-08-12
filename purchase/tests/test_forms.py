from django.contrib.auth.models import User
from django.test import TestCase

from core.models import PurchaseAssignment, Supplier
from purchase.forms import PurchaseReceiptForm


class PurchaseReceiptFormTests(TestCase):
    def test_supplier_input_options_include_buyer_label(self):
        user = User.objects.create_user("buyer-a")
        supplier = Supplier.objects.create(name="供应商 A")
        PurchaseAssignment.objects.create(user=user, supplier=supplier)

        form = PurchaseReceiptForm(user=user)

        self.assertEqual(form.fields["supplier"].widget.attrs["list"], "purchase-supplier-options")
        self.assertIn("供应商 A（buyer-a）", form.supplier_options)
