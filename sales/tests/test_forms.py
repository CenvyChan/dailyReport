from django.contrib.auth.models import User
from django.test import TestCase

from core.models import Customer, SalesAssignment
from core.testing import company_a, company_b
from sales.forms import SalesShipmentForm


class SalesShipmentFormTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("sales-a")

    def test_customer_input_options_include_salesperson_label(self):
        customer = Customer.objects.create(company=company_a(), name="客户 A")
        SalesAssignment.objects.create(user=self.user, customer=customer)

        form = SalesShipmentForm(user=self.user, company=company_a())

        self.assertEqual(form.fields["customer"].widget.attrs["list"], "sales-customer-options")
        self.assertIn("客户 A（sales-a）", form.customer_options)

    def test_options_exclude_customers_belonging_to_another_company(self):
        SalesAssignment.objects.create(
            user=self.user, customer=Customer.objects.create(company=company_b(), name="客户 B 家")
        )

        form = SalesShipmentForm(user=self.user, company=company_a())

        self.assertEqual(form.customer_options, [])
