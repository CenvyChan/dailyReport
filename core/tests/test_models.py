from datetime import date

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase

from core.models import Customer, ExchangeRate, SalesAssignment
from core.testing import company_a, company_b


class ExchangeRateTests(TestCase):
    def test_rate_month_must_be_first_day(self):
        rate = ExchangeRate(company=company_a(), month=date(2026, 8, 10), usd_to_cny="6.8067")
        with self.assertRaises(ValidationError):
            rate.full_clean()

    def test_same_month_can_hold_a_different_rate_per_company(self):
        ExchangeRate.objects.create(company=company_a(), month=date(2026, 8, 1), usd_to_cny="7.1200")
        ExchangeRate.objects.create(company=company_b(), month=date(2026, 8, 1), usd_to_cny="7.2500")

        self.assertEqual(ExchangeRate.objects.filter(month=date(2026, 8, 1)).count(), 2)


class CustomerIsolationTests(TestCase):
    def test_same_customer_name_can_exist_in_both_companies(self):
        Customer.objects.create(company=company_a(), name="客户 A")
        Customer.objects.create(company=company_b(), name="客户 A")

        self.assertEqual(Customer.objects.filter(name="客户 A").count(), 2)


class AssignmentTests(TestCase):
    def test_customer_assignment_is_unique_per_user_and_customer(self):
        user = User.objects.create_user("sales-a")
        customer = Customer.objects.create(company=company_a(), name="客户 A")
        SalesAssignment.objects.create(user=user, customer=customer)
        duplicate = SalesAssignment(user=user, customer=customer)
        with self.assertRaises(ValidationError):
            duplicate.full_clean()
