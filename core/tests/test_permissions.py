from django.contrib.auth.models import Group, User
from django.test import TestCase

from core.models import Customer, SalesAssignment
from core.services.permissions import customer_queryset_for
from core.testing import company_a, company_b


class CustomerScopeTests(TestCase):
    def setUp(self):
        self.sales = User.objects.create_user("sales-a")
        sales_group, _ = Group.objects.get_or_create(name="sales")
        self.sales.groups.add(sales_group)

    def test_sales_user_only_receives_assigned_customers(self):
        assigned = Customer.objects.create(company=company_a(), name="客户 A")
        Customer.objects.create(company=company_a(), name="客户 B")
        SalesAssignment.objects.create(user=self.sales, customer=assigned)

        self.assertEqual(list(customer_queryset_for(self.sales, company_a())), [assigned])

    def test_customers_assigned_in_another_company_are_not_visible(self):
        other = Customer.objects.create(company=company_b(), name="客户 B 家")
        SalesAssignment.objects.create(user=self.sales, customer=other)

        self.assertEqual(list(customer_queryset_for(self.sales, company_a())), [])
        self.assertEqual(list(customer_queryset_for(self.sales, company_b())), [other])

    def test_administrator_still_only_sees_the_active_company(self):
        admin = User.objects.create_superuser("admin", password="pw")
        in_a = Customer.objects.create(company=company_a(), name="客户 A")
        Customer.objects.create(company=company_b(), name="客户 B")

        self.assertEqual(list(customer_queryset_for(admin, company_a())), [in_a])

    def test_missing_company_returns_nothing(self):
        Customer.objects.create(company=company_a(), name="客户 A")

        self.assertEqual(list(customer_queryset_for(self.sales, None)), [])
