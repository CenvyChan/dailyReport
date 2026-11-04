from datetime import datetime
from decimal import Decimal
from unittest.mock import Mock, patch
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from core.testing import company_a, company_b
from integrations.models import DingtalkApp, DingtalkApprovalInstance, DingtalkCompanyMapping, DingtalkProcessConfig
from integrations.services.expense_summary import analyze_expenses, expense_snapshot_key
from integrations.tests.test_expense_fields import reimbursement_form


class ExpenseCollectionTests(TestCase):
    def setUp(self):
        self.a, self.b = company_a(), company_b()
        self.app = DingtalkApp.objects.create(company=self.a, name="app", app_key="test", app_secret="test")
        DingtalkCompanyMapping.objects.create(app=self.app, application_company="Company A", company=self.a)
        DingtalkCompanyMapping.objects.create(app=self.app, application_company="Company B", company=self.b)
        self.salary = DingtalkProcessConfig.objects.create(
            app=self.app, name="员工薪资发放申请A", process_code="salary", amount_component="付款总额"
        )
        self.reimburse = DingtalkProcessConfig.objects.create(
            app=self.app, name="日常报销单据", process_code="reimburse", amount_component="报销金额（元）"
        )

    def mock_client(self, unknown=False):
        client = Mock()
        client.list_instance_ids.side_effect = [["s1"], ["r1"]]
        client.get_instance.side_effect = [
            {
                "form_component_values": {"申请公司": "Unknown" if unknown else "Company A", "付款总额": "100"},
                "create_time": "2026-10-10 12:00:00",
                "status": "COMPLETED",
                "result": "agree",
            },
            {
                "form_component_values": reimbursement_form(company="Company B"),
                "create_time": "2026-10-31 12:00:00",
                "status": "COMPLETED",
                "result": "refuse",
            },
        ]
        return client

    def test_collect_preserves_company_and_month_and_does_not_send(self):
        with patch(
            "integrations.management.commands.sync_expense_approvals.DingtalkClient", return_value=self.mock_client()
        ):
            call_command("sync_expense_approvals", app_id=self.app.pk, period="2026-10", stdout=StringIO())
        self.assertEqual(DingtalkApprovalInstance.objects.count(), 2)
        start = timezone.make_aware(datetime(2026, 10, 1))
        end = timezone.make_aware(datetime(2026, 11, 1))
        configs = [self.salary, self.reimburse]
        a = analyze_expenses(self.a, start, end, configs)
        b = analyze_expenses(self.b, start, end, configs)
        self.assertEqual(a["summary"]["total_amount"], Decimal(100))
        self.assertEqual(b["summary"]["total_amount"], Decimal(30))
        self.assertEqual(a["summary"]["approved_amount"], Decimal(100))
        self.assertEqual(b["summary"]["approved_amount"], Decimal(0))
        self.assertEqual(b["summary"]["rejected_amount"], Decimal(30))
        self.assertIsNone(a["summary"]["paid_amount"])
        self.assertEqual([source["count"] for source in a["sources"]], [1, 0])
        self.assertNotIn("private", str(a))
        self.assertTrue(expense_snapshot_key(configs).startswith("expense:"))

    def test_dryrun_and_unknown_preflight_do_not_write(self):
        with patch(
            "integrations.management.commands.sync_expense_approvals.DingtalkClient", return_value=self.mock_client()
        ):
            call_command(
                "sync_expense_approvals", app_id=self.app.pk, period="2026-10", dry_run=True, stdout=StringIO()
            )
        self.assertEqual(DingtalkApprovalInstance.objects.count(), 0)
        with (
            patch(
                "integrations.management.commands.sync_expense_approvals.DingtalkClient",
                return_value=self.mock_client(unknown=True),
            ),
            self.assertRaisesRegex(CommandError, "尚未写入"),
        ):
            call_command("sync_expense_approvals", app_id=self.app.pk, period="2026-10", stdout=StringIO())
        self.assertEqual(DingtalkApprovalInstance.objects.count(), 0)
