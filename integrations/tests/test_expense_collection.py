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


class ReimbursementReportMappingTests(TestCase):
    def setUp(self):
        self.a, self.b = company_a(), company_b()
        self.app = DingtalkApp.objects.create(company=self.a, name="app", app_key="test", app_secret="test")
        DingtalkCompanyMapping.objects.create(app=self.app, application_company="Company B", company=self.b)
        self.process = DingtalkProcessConfig.objects.create(
            app=self.app, name="日常报销单据", process_code="reimburse", amount_component="报销金额（元）"
        )
        self.start = timezone.make_aware(datetime(2026, 10, 1))
        self.end = timezone.make_aware(datetime(2026, 11, 1))

    def report(self):
        return analyze_expenses(self.b, self.start, self.end, [self.process])

    def test_owner_and_expense_descriptions_override_payment_fields(self):
        from integrations.services.payment_organizations import save_approval

        form = reimbursement_form()
        form += [{"name": "收款人", "value": "旧付款收款人"}, {"name": "备注", "value": "非费用说明"}]
        form[1]["value"].append(
            {"props": {"label": "归属人"}, "value": "归属人员甲", "extValue": [{"name": "归属人员甲", "emplId": "ID"}]}
        )
        reasons = ["交通费用", "住宿费用" + "说明" * 70]
        for row, reason in zip(form[1]["value"][0]["value"], reasons, strict=True):
            row["rowValue"][1]["value"] = reason
        save_approval(
            self.app,
            self.process,
            {
                "form_component_values": form,
                "originator_name": "申请人乙",
                "create_time": "2026-10-15 12:00:00",
                "status": "RUNNING",
            },
            "reimbursement-id",
        )
        data = self.report()
        self.assertEqual(data["summary"]["total_amount"], Decimal(30))
        self.assertEqual(data["summary"]["total_count"], 1)
        self.assertEqual(data["by_recipient"][0]["recipient"], "归属人员甲")
        self.assertEqual(data["by_recipient"][0]["details"][0]["reason"], "；".join(reasons))
        self.assertEqual(data["by_recipient"][0]["details"][0]["originator"], "申请人乙")
        from io import BytesIO
        from openpyxl import load_workbook
        from integrations.services.payment_excel import export_payment_excel_bytes

        period = {"label": "2026年10月", "start_date": self.start.date(), "end_date": self.end.date()}
        book = load_workbook(BytesIO(export_payment_excel_bytes(data, period)))
        exported = list(book["详细清单"].values)[1]
        self.assertEqual(exported[1], "归属人员甲")
        self.assertEqual(exported[3], "；".join(reasons))
        book.close()

    def test_missing_owner_does_not_fall_back_to_applicant(self):
        from integrations.services.payment_organizations import save_approval

        save_approval(
            self.app,
            self.process,
            {
                "form_component_values": reimbursement_form(),
                "originator_name": "申请人乙",
                "create_time": "2026-10-15 12:00:00",
            },
            "missing-owner",
        )
        self.assertEqual(self.report()["by_recipient"][0]["recipient"], "归属人未填写")

    def test_legacy_normalized_record_reads_owner_from_saved_raw(self):
        from integrations.services.payment_organizations import save_approval

        form = reimbursement_form()
        form[1]["value"].append({"props": {"label": "归属人"}, "value": "归属人员丙"})
        record, _, _ = save_approval(
            self.app,
            self.process,
            {"form_component_values": form, "create_time": "2026-10-15 12:00:00"},
            "legacy-record",
        )
        record.form_values["__expense"].pop("owner_name", None)
        record.save(update_fields=["form_values"])
        self.assertEqual(self.report()["by_recipient"][0]["recipient"], "归属人员丙")
