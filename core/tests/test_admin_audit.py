from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Customer, OperationLog, Supplier
from purchase.models import PurchaseReceipt
from sales.models import SalesShipment


class CoreAdminAuditTests(TestCase):
    def test_admin_customer_create_is_written_to_operation_log(self):
        admin = User.objects.create_superuser("admin", password="pw")
        self.client.force_login(admin)

        response = self.client.post(reverse("admin:core_customer_add"), {"name": "客户 A", "is_active": "on"})

        self.assertRedirects(response, reverse("admin:core_customer_changelist"))
        customer = Customer.objects.get(name="客户 A")
        self.assertTrue(OperationLog.objects.filter(action="CREATE", object_id=str(customer.pk)).exists())

    def test_sales_and_purchase_admin_updates_are_written_to_operation_log(self):
        admin = User.objects.create_superuser("admin", password="pw")
        owner = User.objects.create_user("sales-a")
        buyer = User.objects.create_user("buyer-a")
        customer = Customer.objects.create(name="客户 A")
        supplier = Supplier.objects.create(name="供应商 A")
        shipment = SalesShipment.objects.create(
            customer=customer,
            owner=owner,
            sale_type="DOMESTIC",
            shipment_date=date(2026, 8, 10),
            quantity=1,
            currency="CNY",
            original_amount="10",
            exchange_rate="1",
            amount_cny="10",
        )
        receipt = PurchaseReceipt.objects.create(
            supplier=supplier,
            buyer=buyer,
            purchase_type="DOMESTIC",
            purchase_date=date(2026, 8, 10),
            quantity=1,
            currency="CNY",
            original_amount="10",
            exchange_rate="1",
            amount_cny="10",
        )
        self.client.force_login(admin)

        response = self.client.post(
            reverse("admin:sales_salesshipment_change", args=[shipment.pk]),
            {
                "customer": customer.pk,
                "owner": owner.pk,
                "sale_type": "DOMESTIC",
                "shipment_date": "2026-08-10",
                "quantity": "2",
                "original_amount": "10",
                "exchange_rate": "1",
                "amount_cny": "10",
                "source": "MANUAL",
                "source_file": "",
                "import_batch": "",
                "source_row": "",
            },
        )
        self.assertRedirects(response, reverse("admin:sales_salesshipment_changelist"))

        response = self.client.post(
            reverse("admin:purchase_purchasereceipt_change", args=[receipt.pk]),
            {
                "supplier": supplier.pk,
                "buyer": buyer.pk,
                "purchase_type": "DOMESTIC",
                "purchase_date": "2026-08-10",
                "quantity": "2",
                "original_amount": "10",
                "exchange_rate": "1",
                "amount_cny": "10",
                "source": "MANUAL",
                "source_file": "",
                "import_batch": "",
                "source_row": "",
            },
        )
        self.assertRedirects(response, reverse("admin:purchase_purchasereceipt_changelist"))

        self.assertTrue(
            OperationLog.objects.filter(
                action="UPDATE", model_label="sales.SalesShipment", object_id=str(shipment.pk)
            ).exists()
        )
        self.assertTrue(
            OperationLog.objects.filter(
                action="UPDATE", model_label="purchase.PurchaseReceipt", object_id=str(receipt.pk)
            ).exists()
        )
