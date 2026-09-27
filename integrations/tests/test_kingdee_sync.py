from datetime import date
from decimal import Decimal
from unittest import mock

from django.test import TestCase

from core.models import Customer
from core.testing import company_a
from integrations.models import (
    BusinessType,
    KingdeeAccount,
    KingdeeFormConfig,
    KingdeeOrgBinding,
    KingdeePartyMapping,
    StockTransaction,
    StockTransactionLine,
    SyncRun,
)
from integrations.services import kingdee_sync


def _row(config, **role_values):
    """按 config.field_map() 的角色顺序拼一行，模拟 ExecuteBillQuery 的二维数组。"""
    return [role_values.get(role, "") for role in config.field_map().keys()]


class KingdeeSyncTests(TestCase):
    def setUp(self):
        self.company = company_a()
        self.account = KingdeeAccount.objects.create(
            name="acc", server_url="http://x/k3cloud", acct_id="1", username="u", app_id="a", app_secret="s"
        )
        self.binding = KingdeeOrgBinding.objects.create(
            company=self.company, account=self.account, org_number="ORG01"
        )
        KingdeeFormConfig.objects.filter(business_type=BusinessType.PURCHASE_IN).delete()
        self.config = KingdeeFormConfig.objects.get(business_type=BusinessType.SALES_OUT)
        self.config.fld_party_number = "FCustId.FNumber"
        self.config.fld_party_name = "FCustId.FName"
        self.config.save()
        self.today = date(2026, 9, 24)

    def _run(self, specs, as_of=None, dry_run=False):
        rows = [_row(self.config, **s) for s in specs]
        with mock.patch.object(kingdee_sync.kingdee_client, "build_sdk", return_value=object()), mock.patch.object(
            kingdee_sync.kingdee_client, "query_bill", return_value=rows
        ) as qb:
            results = kingdee_sync.sync_kingdee(as_of=as_of or self.today, company=self.company, dry_run=dry_run)
        return results, qb

    def _line(self, fid, entry, day="2026-09-10", **extra):
        base = {"fid": fid, "entry_id": entry, "bill_no": f"XSCK{fid}", "date": day, "status": "C"}
        base.update(extra)
        return base

    def test_upsert_creates_headers_and_lines(self):
        specs = [
            self._line("1", "E1", qty="2", amount="200", price="100", material_number="M1", material_name="物料1"),
            self._line("1", "E2", qty="3", amount="300", price="100", material_number="M2", material_name="物料2"),
            self._line("2", "E3", qty="1", amount="50", price="50", material_number="M1", material_name="物料1"),
        ]
        self._run(specs)
        self.assertEqual(StockTransaction.objects.filter(company=self.company).count(), 2)
        self.assertEqual(StockTransactionLine.objects.count(), 3)
        txn1 = StockTransaction.objects.get(fid="1")
        self.assertEqual(txn1.total_amount, Decimal("500"))
        self.assertEqual(txn1.total_quantity, Decimal("5"))
        self.assertTrue(SyncRun.objects.filter(status=SyncRun.Status.SUCCESS).exists())

    def test_rerun_is_idempotent_by_fid(self):
        specs = [self._line("1", "E1", qty="2", amount="200"), self._line("2", "E2", qty="1", amount="50")]
        self._run(specs)
        self._run(specs)
        self.assertEqual(StockTransaction.objects.filter(company=self.company).count(), 2)
        self.assertEqual(StockTransactionLine.objects.count(), 2)

    def test_missing_fid_in_window_is_disabled(self):
        self._run([self._line("1", "E1"), self._line("2", "E2")])
        # 第二次只回来 fid=1 → fid=2 被软删
        self._run([self._line("1", "E1")])
        self.assertTrue(StockTransaction.objects.get(fid="1").is_active)
        txn2 = StockTransaction.objects.get(fid="2")
        self.assertFalse(txn2.is_active)
        self.assertIsNotNone(txn2.disabled_at)

    def test_out_of_window_txn_not_disabled(self):
        # 上月单据不在当前月窗口内，重拉当前月不应误删
        old = StockTransaction.objects.create(
            company=self.company, business_type=BusinessType.SALES_OUT, form_id=self.config.form_id,
            fid="OLD", biz_date=date(2026, 8, 15), is_active=True,
        )
        self._run([self._line("1", "E1")])
        old.refresh_from_db()
        self.assertTrue(old.is_active)

    def test_filter_string_scopes_month_status_org(self):
        _, qb = self._run([self._line("1", "E1")])
        filter_string = qb.call_args.kwargs["filter_string"]
        self.assertIn("FDate >= '2026-09-01'", filter_string)
        self.assertIn("FDate < '2026-09-24'", filter_string)
        self.assertIn("FDocumentStatus = 'C'", filter_string)
        self.assertIn("FStockOrgId.FNumber = 'ORG01'", filter_string)

    def test_party_auto_match_links_customer(self):
        customer = Customer.objects.create(company=self.company, name="华为")
        self._run([self._line("1", "E1", party_number="C001", party_name="华为技术有限公司")])
        mapping = KingdeePartyMapping.objects.get(company=self.company, k3_number="C001")
        self.assertEqual(mapping.match_status, "AUTO")
        self.assertEqual(mapping.customer_id, customer.id)
        self.assertEqual(StockTransaction.objects.get(fid="1").party_id, mapping.id)

    def test_party_multiple_candidates_pending(self):
        Customer.objects.create(company=self.company, name="华为")
        Customer.objects.create(company=self.company, name="华为科技")
        self._run([self._line("1", "E1", party_number="C001", party_name="华为技术有限公司")])
        mapping = KingdeePartyMapping.objects.get(company=self.company, k3_number="C001")
        self.assertEqual(mapping.match_status, "PENDING")
        self.assertIsNone(mapping.customer_id)
        self.assertGreaterEqual(len(mapping.candidates), 2)

    def test_dry_run_writes_nothing(self):
        _, qb = self._run([self._line("1", "E1")], dry_run=True)
        qb.assert_called()
        self.assertEqual(StockTransaction.objects.count(), 0)
        self.assertFalse(SyncRun.objects.exists())

    def test_month_window_override(self):
        # 手动补拉整月：显式窗口覆盖"当前月"模式，过滤用 [月初, 次月初)，且 5 月单据落库
        rows = [_row(self.config, **self._line("50", "E50", day="2026-05-31", qty="1", amount="10"))]
        with mock.patch.object(kingdee_sync.kingdee_client, "build_sdk", return_value=object()), mock.patch.object(
            kingdee_sync.kingdee_client, "query_bill", return_value=rows
        ) as qb:
            kingdee_sync.sync_kingdee(
                as_of=self.today, company=self.company, window_override=(date(2026, 5, 1), date(2026, 6, 1))
            )
        fs = qb.call_args.kwargs["filter_string"]
        self.assertIn("FDate >= '2026-05-01'", fs)
        self.assertIn("FDate < '2026-06-01'", fs)
        self.assertTrue(StockTransaction.objects.filter(fid="50", biz_date=date(2026, 5, 31)).exists())
        run = SyncRun.objects.filter(status=SyncRun.Status.SUCCESS).first()
        self.assertEqual((run.window_start, run.window_end), (date(2026, 5, 1), date(2026, 6, 1)))
