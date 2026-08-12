from django.contrib.auth.models import User
from django.test import TestCase

from core.models import Customer, SalesAssignment
from sales.forms import SalesShipmentForm


class SalesShipmentFormTests(TestCase):
    def test_customer_input_options_include_salesperson_label(self):
        user = User.objects.create_user("sales-a")
        customer = Customer.objects.create(name="客户 A")
        SalesAssignment.objects.create(user=user, customer=customer)

        form = SalesShipmentForm(user=user)

        self.assertEqual(form.fields["customer"].widget.attrs["list"], "sales-customer-options")
        self.assertIn("客户 A（sales-a）", form.customer_options)
