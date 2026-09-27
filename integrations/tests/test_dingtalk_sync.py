from decimal import Decimal

from django.test import TestCase

from core.testing import company_a
from integrations.models import (
    DingtalkApp,
    DingtalkApprovalInstance,
    DingtalkProcessConfig,
    SyncRun,
)
from integrations.services import dingtalk_sync


class FakeClient:
    def __init__(self, app):
        self.app = app

    def list_instance_ids(self, process_code, start_ms, end_ms):
        return ["PID1", "PID2"]

    def get_instance(self, pid):
        return {
            "business_id": pid,
            "title": f"付款申请-{pid}",
            "status": "COMPLETED",
            "result": "agree",
            "originator_userid": "u1",
            "originator_dept_name": "财务部",
            "create_time": "2026-09-10 09:00:00",
            "finish_time": "2026-09-11 10:00:00",
            "form_component_values": [
                {"name": "付款金额", "value": "1234.50"},
                {"name": "事由", "value": "办公用品"},
            ],
        }


class DingtalkSyncTests(TestCase):
    def setUp(self):
        self.company = company_a()
        self.app = DingtalkApp.objects.create(company=self.company, app_key="k", app_secret="s")
        DingtalkProcessConfig.objects.create(
            app=self.app, process_code="PROC-PAY", name="付款申请", amount_component="付款金额"
        )

    def test_sync_upserts_and_extracts_amount(self):
        dingtalk_sync.sync_dingtalk(company=self.company, client_factory=FakeClient)
        self.assertEqual(DingtalkApprovalInstance.objects.filter(company=self.company).count(), 2)
        inst = DingtalkApprovalInstance.objects.get(process_instance_id="PID1")
        self.assertEqual(inst.amount, Decimal("1234.50"))
        self.assertEqual(inst.form_values["事由"], "办公用品")
        self.assertEqual(inst.dept_name, "财务部")
        self.assertTrue(
            SyncRun.objects.filter(integration=SyncRun.Integration.DINGTALK, status=SyncRun.Status.SUCCESS).exists()
        )

    def test_rerun_is_idempotent(self):
        dingtalk_sync.sync_dingtalk(company=self.company, client_factory=FakeClient)
        dingtalk_sync.sync_dingtalk(company=self.company, client_factory=FakeClient)
        self.assertEqual(DingtalkApprovalInstance.objects.count(), 2)

    def test_dry_run_writes_nothing(self):
        dingtalk_sync.sync_dingtalk(company=self.company, client_factory=FakeClient, dry_run=True)
        self.assertEqual(DingtalkApprovalInstance.objects.count(), 0)
        self.assertFalse(SyncRun.objects.exists())
