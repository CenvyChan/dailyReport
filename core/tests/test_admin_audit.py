from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Customer, OperationLog, Supplier
from core.testing import company_a
from purchase.models import PurchaseReceipt
from sales.models import SalesShipment


class CoreAdminAuditTests(TestCase):
    def test_admin_customer_create_is_written_to_operation_log(self):
        admin = User.objects.create_superuser("admin", password="pw")
        self.client.force_login(admin)

        response = self.client.post(
            reverse("admin:core_customer_add"),
            {"company": company_a().pk, "name": "客户 A", "is_active": "on"},
        )

        self.assertRedirects(response, reverse("admin:core_customer_changelist"))
        customer = Customer.objects.get(name="客户 A")
        self.assertTrue(OperationLog.objects.filter(action="CREATE", object_id=str(customer.pk)).exists())

    def test_sales_and_purchase_admin_updates_are_written_to_operation_log(self):
        admin = User.objects.create_superuser("admin", password="pw")
        owner = User.objects.create_user("sales-a")
        buyer = User.objects.create_user("buyer-a")
        company = company_a()
        customer = Customer.objects.create(company=company, name="客户 A")
        supplier = Supplier.objects.create(company=company, name="供应商 A")
        shipment = SalesShipment.objects.create(
            company=company,
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
            company=company,
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
                "company": company.pk,
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
                "company": company.pk,
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


class DingtalkGroupAdminAuditTests(TestCase):
    def setUp(self):
        from core.models import Company
        from integrations.models import DingtalkApp, DingtalkCompanyMapping, DingtalkGroupConfig

        self.client.force_login(User.objects.create_superuser("group-admin", password="pw"))
        self.company = company_a()
        self.other_company = Company.objects.create(code="AUDIT-NBHH", name="审计测试公司")
        self.app = DingtalkApp.objects.create(
            company=self.company, name="审计测试应用", app_key="audit-key", app_secret="audit-secret"
        )
        DingtalkCompanyMapping.objects.create(
            app=self.app, company=self.other_company, application_company=self.other_company.name
        )
        self.group = DingtalkGroupConfig.objects.create(
            company=self.company, app=self.app, name="同群多公司",
            open_conversation_id="cid-audit", send_at="18:00", payment_report_types=[]
        )
        self.group.companies.set([self.company, self.other_company])

    def _payload(self):
        return {
            "companies": [self.company.pk, self.other_company.pk],
            "app": self.app.pk, "name": "同群多公司",
            "open_conversation_id": "cid-audit", "send_at": "18:00",
            "content_types": ["APPROVALS"], "payment_report_types": ["week", "month"],
            "is_active": "on", "_save": "保存",
        }

    def test_week_and_month_save_with_existing_company_multiselection(self):
        response = self.client.post(
            reverse("admin:integrations_dingtalkgroupconfig_change", args=[self.group.pk]),
            self._payload(),
        )
        self.assertEqual(response.status_code, 302, response.context["adminform"].form.errors if response.context else response.content)
        self.assertRedirects(response, reverse("admin:integrations_dingtalkgroupconfig_changelist"))
        self.group.refresh_from_db()
        self.assertEqual(self.group.payment_report_types, ["week", "month"])
        self.assertEqual(set(self.group.companies.values_list("pk", flat=True)),
                         {self.company.pk, self.other_company.pk})
        audit = OperationLog.objects.get(model_label="integrations.DingtalkGroupConfig",
                                         object_id=str(self.group.pk), action="UPDATE")
        self.assertEqual(set(audit.before_data["companies"]),
                         {self.company.pk, self.other_company.pk})
        self.assertEqual(audit.after_data["payment_report_types"], ["week", "month"])

    def test_company_multiselection_can_be_changed_and_saved_again(self):
        payload = self._payload()
        payload["companies"] = [self.other_company.pk]
        url = reverse("admin:integrations_dingtalkgroupconfig_change", args=[self.group.pk])
        for _ in range(2):
            response = self.client.post(url, payload)
            self.assertRedirects(response, reverse("admin:integrations_dingtalkgroupconfig_changelist"))
        self.group.refresh_from_db()
        self.assertEqual(self.group.payment_report_types, ["week", "month"])
        self.assertEqual(list(self.group.companies.values_list("pk", flat=True)),
                         [self.other_company.pk])
