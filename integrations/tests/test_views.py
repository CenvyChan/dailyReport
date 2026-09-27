from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.testing import company_a, login_with_company
from integrations.models import BusinessType, StockTransaction


class IntegrationViewsSmokeTests(TestCase):
    def setUp(self):
        self.company = company_a()
        self.admin = User.objects.create_superuser("admin-a", "a@a.com", "pw12345678")
        login_with_company(self.client, self.admin, self.company)
        self.txn = StockTransaction.objects.create(
            company=self.company, business_type=BusinessType.SALES_OUT, form_id="SAL_OUTSTOCK",
            fid="1", bill_no="XSCK1", biz_date=date(2026, 9, 10), total_amount=Decimal("100"),
        )

    def test_pages_render(self):
        for name in ("reconciliation", "stock_list", "approval_list", "party_mapping"):
            resp = self.client.get(reverse(f"integrations:{name}"))
            self.assertEqual(resp.status_code, 200, name)

    def test_stock_detail_renders(self):
        resp = self.client.get(reverse("integrations:stock_detail", args=[self.txn.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_party_mapping_requires_admin(self):
        viewer = User.objects.create_user("viewer-a", password="pw12345678")
        login_with_company(self.client, viewer, self.company)
        resp = self.client.get(reverse("integrations:party_mapping"))
        self.assertEqual(resp.status_code, 403)
