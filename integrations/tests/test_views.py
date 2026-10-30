from datetime import date
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Customer, SalesAssignment
from core.testing import company_a, login_with_company
from integrations.models import (
    BusinessType,
    KingdeePartyMapping,
    ReportSnapshot,
    StockTransaction,
)
from integrations.services.report_delivery import public_snapshot_url


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

    def test_party_mapping_denied_without_access(self):
        viewer = User.objects.create_user("viewer-a", password="pw12345678")
        login_with_company(self.client, viewer, self.company)
        resp = self.client.get(reverse("integrations:party_mapping"))
        self.assertEqual(resp.status_code, 403)


class PartyMappingClaimTests(TestCase):
    """业务员认领：只看/只改自己负责范围内的客商映射，只增不减。"""

    def setUp(self):
        self.company = company_a()
        self.mine = Customer.objects.create(company=self.company, name="我的客户")
        self.other = Customer.objects.create(company=self.company, name="别人客户")
        self.sales = User.objects.create_user("sales-a", password="pw12345678")
        SalesAssignment.objects.create(user=self.sales, customer=self.mine)
        login_with_company(self.client, self.sales, self.company)

    def _mapping(self, k3_number, k3_name, candidates, **extra):
        extra.setdefault("match_status", KingdeePartyMapping.MatchStatus.PENDING)
        return KingdeePartyMapping.objects.create(
            company=self.company, party_type=KingdeePartyMapping.PartyType.CUSTOMER,
            k3_number=k3_number, k3_name=k3_name, candidates=candidates, **extra,
        )

    def _post(self, mapping, choice, return_status="PENDING"):
        return self.client.post(
            reverse("integrations:party_mapping"),
            {"mapping_id": mapping.id, "choice": choice, "return_status": return_status},
        )

    def test_salesperson_sees_only_in_range(self):
        mine = self._mapping("C1", "我的客户全称", [{"id": self.mine.id, "name": "我的客户", "score": 0.95}])
        other = self._mapping("C2", "别人客户全称", [{"id": self.other.id, "name": "别人客户", "score": 0.95}])
        resp = self.client.get(reverse("integrations:party_mapping"))
        ids = [m.id for m in resp.context["page"].object_list]
        self.assertIn(mine.id, ids)
        self.assertNotIn(other.id, ids)

    def test_salesperson_claim_own_candidate(self):
        m = self._mapping("C1", "我的客户全称", [{"id": self.mine.id, "name": "我的客户", "score": 0.95}])
        resp = self._post(m, self.mine.id)
        self.assertEqual(resp.status_code, 302)
        m.refresh_from_db()
        self.assertEqual(m.match_status, "MANUAL")
        self.assertEqual(m.customer_id, self.mine.id)

    def test_salesperson_cannot_claim_others(self):
        m = self._mapping("C2", "别人客户全称", [{"id": self.other.id, "name": "别人客户", "score": 0.95}])
        self._post(m, self.other.id)
        m.refresh_from_db()
        self.assertEqual(m.match_status, "PENDING")
        self.assertIsNone(m.customer_id)

    def test_salesperson_cannot_modify_others_linked(self):
        m = self._mapping("C2", "别人客户全称", [], customer=self.other,
                          match_status=KingdeePartyMapping.MatchStatus.MANUAL)
        self._post(m, self.mine.id, return_status="ALL")
        m.refresh_from_db()
        self.assertEqual(m.customer_id, self.other.id)
        self.assertEqual(m.match_status, "MANUAL")

    def test_salesperson_cannot_clear(self):
        m = self._mapping("C1", "我的客户全称", [], customer=self.mine,
                          match_status=KingdeePartyMapping.MatchStatus.MANUAL)
        self._post(m, "", return_status="ALL")
        m.refresh_from_db()
        self.assertEqual(m.customer_id, self.mine.id)
        self.assertEqual(m.match_status, "MANUAL")


class PartyMappingAdminTests(TestCase):
    def setUp(self):
        self.company = company_a()
        self.customer = Customer.objects.create(company=self.company, name="客户A")
        self.admin = User.objects.create_superuser("admin-a", "a@a.com", "pw12345678")
        login_with_company(self.client, self.admin, self.company)

    def test_admin_can_clear_and_link_any(self):
        m = KingdeePartyMapping.objects.create(
            company=self.company, party_type=KingdeePartyMapping.PartyType.CUSTOMER,
            k3_number="C1", k3_name="客户A全称",
            match_status=KingdeePartyMapping.MatchStatus.PENDING, candidates=[],
        )
        url = reverse("integrations:party_mapping")
        self.client.post(url, {"mapping_id": m.id, "choice": self.customer.id, "return_status": "PENDING"})
        m.refresh_from_db()
        self.assertEqual(m.customer_id, self.customer.id)
        self.assertEqual(m.match_status, "MANUAL")
        self.client.post(url, {"mapping_id": m.id, "choice": "", "return_status": "ALL"})
        m.refresh_from_db()
        self.assertIsNone(m.customer_id)
        self.assertEqual(m.match_status, "UNMATCHED")


class PublicSnapshotLinkTests(TestCase):
    """钉钉消息里的在线日报链接：签名有效期内免登录，只能看单个快照。"""

    def setUp(self):
        self.company = company_a()
        self.snapshot = ReportSnapshot.objects.create(
            company=self.company, report_date=date(2026, 10, 29), scope="BOTH",
            data={}, is_complete=True,
        )
        self.other = ReportSnapshot.objects.create(
            company=self.company, report_date=date(2026, 10, 28), scope="BOTH",
            data={}, is_complete=True,
        )

    def _token(self, snapshot):
        return parse_qs(urlparse(public_snapshot_url(snapshot)).query)["token"][0]

    def test_valid_link_renders_without_login(self):
        response = self.client.get(
            reverse("integrations:snapshot_public", args=[self.snapshot.pk]),
            {"token": self._token(self.snapshot)},
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertIn("采购 · 销售汇总日报", body)
        self.assertIn('name="viewport"', body)
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")

    def test_bad_or_mismatched_token_is_forbidden(self):
        url = reverse("integrations:snapshot_public", args=[self.snapshot.pk])
        self.assertEqual(self.client.get(url, {"token": "bad"}).status_code, 403)
        self.assertEqual(
            self.client.get(url, {"token": self._token(self.other)}).status_code, 403
        )

    def test_public_page_offers_pdf_and_excel_download_links(self):
        response = self.client.get(
            reverse("integrations:snapshot_public", args=[self.snapshot.pk]),
            {"token": self._token(self.snapshot)},
        )
        body = response.content.decode("utf-8")
        self.assertIn("下载 PDF", body)
        self.assertIn("下载 Excel", body)
        self.assertIn("download=pdf", body)
        self.assertIn("download=excel", body)

    def test_public_downloads_require_the_same_token(self):
        url = reverse("integrations:snapshot_public", args=[self.snapshot.pk])
        token = self._token(self.snapshot)
        excel = self.client.get(url, {"token": token, "download": "excel"})
        self.assertEqual(excel.status_code, 200)
        self.assertIn("spreadsheetml", excel["Content-Type"])
        with patch(
            "integrations.views_snapshot._pdf_bytes", return_value=b"%PDF-test"
        ):
            pdf = self.client.get(url, {"token": token, "download": "pdf"})
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertEqual(pdf.content, b"%PDF-test")
        self.assertEqual(
            self.client.get(url, {"token": "bad", "download": "excel"}).status_code,
            403,
        )
