from django.contrib.auth.models import Group, User
from django.test import TestCase

from core.models import Customer, SalesAssignment
from core.services.permissions import customer_queryset_for


class CustomerScopeTests(TestCase):
    def test_sales_user_only_receives_assigned_customers(self):
        sales = User.objects.create_user("sales-a")
        sales_group, _ = Group.objects.get_or_create(name="sales")
        sales.groups.add(sales_group)
        assigned = Customer.objects.create(name="客户 A")
        Customer.objects.create(name="客户 B")
        SalesAssignment.objects.create(user=sales, customer=assigned)
        self.assertEqual(list(customer_queryset_for(sales)), [assigned])
