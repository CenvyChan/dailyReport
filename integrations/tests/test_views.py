from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Customer, SalesAssignment
from core.testing import company_a, login_with_company
from integrations.models import BusinessType, KingdeePartyMapping, StockTransaction


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
