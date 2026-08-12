from datetime import date

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase

from core.models import Customer, ExchangeRate, SalesAssignment


class ExchangeRateTests(TestCase):
    def test_rate_month_must_be_first_day(self):
        rate = ExchangeRate(month=date(2026, 8, 10), usd_to_cny="6.8067")
        with self.assertRaises(ValidationError):
            rate.full_clean()


class AssignmentTests(TestCase):
    def test_customer_assignment_is_unique_per_user_and_customer(self):
        user = User.objects.create_user("sales-a")
        customer = Customer.objects.create(name="客户 A")
        SalesAssignment.objects.create(user=user, customer=customer)
        duplicate = SalesAssignment(user=user, customer=customer)
        with self.assertRaises(ValidationError):
            duplicate.full_clean()
