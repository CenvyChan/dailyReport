from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from core.models import Customer, ExchangeRate, OperationLog, SalesAssignment
from core.testing import company_a, company_b
from sales.services import create_sales_shipment, sales_queryset_for


class SalesShipmentServiceTests(TestCase):
    def setUp(self):
        self.company = company_a()
        self.user = User.objects.create_user("sales-a")
        self.customer = Customer.objects.create(company=self.company, name="客户 A")
        SalesAssignment.objects.create(user=self.user, customer=self.customer)
        ExchangeRate.objects.create(company=self.company, month=date(2026, 8, 1), usd_to_cny="6.8067")

    def test_export_sale_uses_usd_and_month_rate_snapshot(self):
        shipment = create_sales_shipment(
            actor=self.user,
            company=self.company,
            data={
                "customer": self.customer,
                "sale_type": "EXPORT",
                "shipment_date": date(2026, 8, 10),
                "quantity": 20,
                "original_amount": "100.00",
            },
        )
        self.assertEqual(shipment.currency, "USD")
        self.assertEqual(shipment.exchange_rate, Decimal("6.8067"))
        self.assertEqual(shipment.amount_cny, Decimal("680.67"))
        self.assertEqual(shipment.company, self.company)

    def test_export_sale_uses_the_rate_of_its_own_company(self):
        other = company_b()
        other_customer = Customer.objects.create(company=other, name="客户 A")
        SalesAssignment.objects.create(user=self.user, customer=other_customer)
        ExchangeRate.objects.create(company=other, month=date(2026, 8, 1), usd_to_cny="7.5000")

        shipment = create_sales_shipment(
            actor=self.user,
            company=other,
            data={
                "customer": other_customer,
                "sale_type": "EXPORT",
                "shipment_date": date(2026, 8, 10),
                "quantity": 1,
                "original_amount": "100.00",
            },
        )

        self.assertEqual(shipment.exchange_rate, Decimal("7.5000"))
        self.assertEqual(shipment.amount_cny, Decimal("750.00"))

    def test_customer_from_another_company_is_rejected(self):
        foreign_customer = Customer.objects.create(company=company_b(), name="客户 B")
        SalesAssignment.objects.create(user=self.user, customer=foreign_customer)

        with self.assertRaises(PermissionError):
            create_sales_shipment(
                actor=self.user,
                company=self.company,
                data={
                    "customer": foreign_customer,
                    "sale_type": "DOMESTIC",
                    "shipment_date": date(2026, 8, 10),
                    "quantity": 1,
                    "original_amount": "10.00",
                },
            )

    def test_queryset_never_leaks_across_companies(self):
        create_sales_shipment(
            actor=self.user,
            company=self.company,
            data={
                "customer": self.customer,
                "sale_type": "DOMESTIC",
                "shipment_date": date(2026, 8, 10),
                "quantity": 1,
                "original_amount": "10.00",
            },
        )

        self.assertEqual(sales_queryset_for(self.user, self.company).count(), 1)
        self.assertEqual(sales_queryset_for(self.user, company_b()).count(), 0)
        self.assertEqual(sales_queryset_for(self.user, None).count(), 0)

    def test_administrator_can_import_for_assigned_owner(self):
        admin = User.objects.create_superuser("admin", password="pw")
        shipment = create_sales_shipment(
            actor=admin,
            company=self.company,
            data={
                "customer": self.customer,
                "owner": self.user,
                "sale_type": "DOMESTIC",
                "shipment_date": date(2026, 8, 10),
                "quantity": 1,
                "original_amount": "10.00",
                "source": "HISTORY_IMPORT",
            },
        )
        self.assertEqual(shipment.owner, self.user)

    def test_history_import_is_recorded_as_import(self):
        admin = User.objects.create_superuser("admin", password="pw")
        shipment = create_sales_shipment(
            actor=admin,
            company=self.company,
            data={
                "customer": self.customer,
                "owner": self.user,
                "sale_type": "DOMESTIC",
                "shipment_date": date(2026, 8, 10),
                "quantity": 1,
                "original_amount": "10.00",
                "source": "HISTORY_IMPORT",
            },
        )

        self.assertTrue(
            OperationLog.objects.filter(action="IMPORT", object_id=str(shipment.pk)).exists()
        )
