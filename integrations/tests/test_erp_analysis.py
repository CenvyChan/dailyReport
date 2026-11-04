import json
import tempfile
from datetime import date, datetime, time
from pathlib import Path
from unittest.mock import Mock, patch
from zipfile import ZipFile
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import signing
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from core.testing import company_a, company_b, login_with_company
from integrations.models import (
    DingtalkApp,
    DingtalkGroupConfig,
    ErpAnalysisSchedule,
    ErpAnalysisTask,
    KingdeeAccount,
    KingdeeOrgBinding,
)
from integrations.services.erp_analysis.catalog import REPORT_KINDS, validate_kinds
from integrations.services.erp_analysis.common import number, serializable
from integrations.services.erp_analysis.query import AnalysisQuery, ModuleUnavailable
from integrations.services.erp_analysis.public import SNAPSHOT_SALT, snapshot_token
from integrations.services.erp_analysis.runner import enqueue, enqueue_due, notify, process_task
from integrations.services.erp_analysis.sources import Normalizer, PURCHASE_SCHEMA, SALES_SCHEMA, analyze
from integrations.services.kingdee_client import KingdeeError


class QueryTests(SimpleTestCase):
    def test_nested_failure_is_not_empty_success(self):
        sdk = Mock()
        sdk.ExecuteBillQuery.return_value = json.dumps(
            [[{"Result": {"ResponseStatus": {"IsSuccess": False, "Errors": [{"Message": "字段错误"}]}}}]]
        )
        with self.assertRaisesRegex(KingdeeError, "字段错误"):
            AnalysisQuery(sdk).bill("X", "A", "")

    def test_module_not_purchased_has_distinct_status(self):
        sdk = Mock()
        sdk.PostJson.return_value = {
            "Result": {"ResponseStatus": {"IsSuccess": False, "Errors": [{"Message": "模块未购买"}]}}
        }
        with self.assertRaises(ModuleUnavailable):
            AnalysisQuery(sdk).report("X", "A", {})

    def test_report_result_and_data_envelopes(self):
        for key in ("Result", "Data"):
            sdk = Mock()
            sdk.PostJson.return_value = {key: {"Rows": [["ok"]], "RowCount": 1}}
            self.assertEqual(AnalysisQuery(sdk).report("X", "A", {}), [["ok"]])

    def test_missing_rows_is_error(self):
        sdk = Mock()
        sdk.PostJson.return_value = {"Result": {"ResponseStatus": {"IsSuccess": True}}}
        with self.assertRaisesRegex(KingdeeError, "Rows"):
            AnalysisQuery(sdk).report("X", "A", {})

    def test_report_multiple_pages_and_parameters(self):
        sdk = Mock()
        sdk.PostJson.side_effect = [
            {"Result": {"Rows": [[1], [2]], "RowCount": 3}},
            {"Result": {"Rows": [[3]], "RowCount": 3}},
        ]
        with patch("integrations.services.erp_analysis.query.SERVER_ROW_LIMIT", 2):
            self.assertEqual(AnalysisQuery(sdk).report("X", "A", {"org": "001"}), [[1], [2], [3]])
        params = json.loads(sdk.PostJson.call_args_list[1].args[1]["parameters"][1])
        self.assertEqual(params["StartRow"], 2)
        self.assertEqual(params["Model"], {"org": "001"})

    def test_report_stalled_cursor_is_error(self):
        sdk = Mock()
        sdk.PostJson.return_value = {"Data": {"Rows": [[1], [2]], "RowCount": 4}}
        with (
            patch("integrations.services.erp_analysis.query.SERVER_ROW_LIMIT", 2),
            self.assertRaisesRegex(KingdeeError, "游标"),
        ):
            AnalysisQuery(sdk).report("X", "A", {})

    def test_report_known_rowcount_cannot_stop_early(self):
        sdk = Mock()
        sdk.PostJson.return_value = {"Data": {"Rows": [[1]], "RowCount": 2}}
        with self.assertRaisesRegex(KingdeeError, "不完整"):
            AnalysisQuery(sdk).report("X", "A", {})

    def test_bill_hard_limit_and_bad_width_are_errors(self):
        sdk = Mock()
        sdk.ExecuteBillQuery.return_value = [[1]] * 10000
        with self.assertRaisesRegex(KingdeeError, "10000"):
            AnalysisQuery(sdk).bill("X", "A", "")
        sdk.ExecuteBillQuery.return_value = [[1]]
        with self.assertRaisesRegex(KingdeeError, "列数"):
            AnalysisQuery(sdk).bill("X", "A,B", "")

    def test_bill_cumulative_hard_limit_cannot_look_complete(self):
        sdk = Mock()
        sdk.ExecuteBillQuery.side_effect = [[[1], [2]], [[3], [4]], []]
        with (
            patch("integrations.services.erp_analysis.query.SERVER_ROW_LIMIT", 4),
            patch("integrations.services.erp_analysis.query.PAGE_SIZE", 2),
            self.assertRaisesRegex(KingdeeError, "硬上限"),
        ):
            AnalysisQuery(sdk).bill("X", "A", "")

    def test_org_never_falls_back_to_numeric_number(self):
        sdk = Mock()
        sdk.ExecuteBillQuery.return_value = []
        with self.assertRaisesRegex(KingdeeError, "内部 ID"):
            AnalysisQuery(sdk).organization("001")
        with self.assertRaisesRegex(KingdeeError, "非法"):
            AnalysisQuery(sdk).organization("001' OR 1=1")

    def test_bill_pagination_and_repeat_guard(self):
        sdk = Mock()
        sdk.ExecuteBillQuery.side_effect = [[[1], [2]], [[3]]]
        with patch("integrations.services.erp_analysis.query.PAGE_SIZE", 2):
            self.assertEqual(AnalysisQuery(sdk).bill("X", "A", ""), [[1], [2], [3]])
        self.assertEqual(sdk.ExecuteBillQuery.call_args.args[0]["StartRow"], 2)
        sdk.ExecuteBillQuery.side_effect = None
        sdk.ExecuteBillQuery.return_value = [[1], [2]]
        with (
            patch("integrations.services.erp_analysis.query.PAGE_SIZE", 2),
            self.assertRaisesRegex(KingdeeError, "游标"),
        ):
            AnalysisQuery(sdk).bill("X", "A", "")


class SourcesTests(SimpleTestCase):
    def setUp(self):
        self.query = Mock()
        self.query.bill.return_value = []
        self.query.report.return_value = []
        self.org = {"number": "001", "id": "100071", "name": "Org"}

    def test_all_six_kinds_generate_empty_report_with_schema(self):
        for kind in REPORT_KINDS:
            result = analyze(kind, self.query, self.org, date(2026, 5, 1), 1)
            self.assertTrue(result["sections"])
            self.assertEqual(result["window"], "2026-05-01 ~ 2026-05-31")

    def test_org_parameter_shapes_and_sales_uppercase_department(self):
        analyze("purchase", self.query, self.org, date(2026, 5, 1), 1)
        self.assertEqual(self.query.report.call_args.args[2]["FPurchaseOrgIdList"], "100071")
        self.assertIn("FDate < '2026-06-01'", self.query.bill.call_args.args[2])
        analyze("inventory", self.query, self.org, date(2026, 5, 1), 1)
        self.assertEqual(self.query.report.call_args.args[2]["FACCTGORGID"], {"FNumber": "001"})
        analyze("sales", self.query, self.org, date(2026, 5, 1), 1)
        model = self.query.report.call_args.args[2]
        self.assertEqual(model["FSaleOrgId"], "100071")
        self.assertEqual(model["FSaleDeptFrom"], {"FNUMBER": ""})

    def test_production_and_subcontract_closed_month_slices(self):
        analyze("production", self.query, self.org, date(2026, 2, 1), 2)
        filters = [call.args[2] for call in self.query.bill.call_args_list]
        self.assertIn("FDate BETWEEN '2026-01-01' AND '2026-01-31'", filters[0])
        self.assertIn("FDate BETWEEN '2026-02-01' AND '2026-02-28'", filters[1])
        self.query.reset_mock()
        analyze("subcontract", self.query, self.org, date(2026, 2, 1), 1)
        wip_call = self.query.bill.call_args
        self.assertEqual(wip_call.args[0], "SUB_PPBOM")
        self.assertNotIn("FDate", wip_call.args[2])
        self.assertIn("FSubOrgId.FNumber = '001'", wip_call.args[2])

    def test_receivable_deduplicates_plan_values_not_just_bill(self):
        self.query.bill.side_effect = [
            [["AR1", "2026/5/4", "C", 100]] * 2,
            [["AR1", 10, 90], ["AR1", "10.00", "90.0"], ["AR1", 20, 80]],
        ]
        result = analyze("receivable", self.query, self.org, date(2026, 5, 1), 1)
        self.assertEqual(result["metrics"]["summary"]["bill_count"], 1)
        self.assertEqual(result["metrics"]["summary"]["unsettled"], 170)

    def test_receivable_leading_zero_guard(self):
        with self.assertRaisesRegex(ValueError, "三位"):
            analyze("receivable", self.query, dict(self.org, number="1"), date(2026, 5, 1), 1)

    def test_merged_purchase_header_and_no_summary_forward_fill(self):
        header = [None] * 26
        header[:5] = ["Org", "PO1", "2026/5/4", "Supplier", "Material"]
        header[8] = 100
        continued = [None] * 26
        continued[4], continued[8] = "Material2", 20
        rows = Normalizer().rows([header, continued, [None] * 26], PURCHASE_SCHEMA, header=(0, 1, 2, 3), detail=(4, 8))
        self.assertEqual(rows[1]["bill"], "PO1")
        self.assertEqual(rows[1]["date"], date(2026, 5, 4))
        self.assertEqual(rows[2]["bill"], "")

    def test_sales_forward_fill_only_nonzero_out_amount(self):
        header = [None] * 19
        header[:7] = ["Org", "S1", "T", "2026/5/4", "P", "C", "M"]
        header[9] = 100
        continued = [None] * 19
        continued[6], continued[9] = "M2", 20
        rows = Normalizer().rows([header, continued, [None] * 19], SALES_SCHEMA, header=(0, 1, 2, 3, 4, 5))
        self.assertEqual(rows[1]["customer"], "C")
        self.assertEqual(rows[2]["bill"], "")

    def test_catalog_rejects_unknown_and_invalid_number(self):
        for value in ([], ["unknown"], ["purchase", "purchase"]):
            with self.assertRaises(ValueError):
                validate_kinds(value)
        with self.assertRaises(ValueError):
            number("NaN")


class TaskAndViewTests(TestCase):
    def setUp(self):
        self.company, self.other = company_a(), company_b()
        self.user = get_user_model().objects.create_user("erp-admin", password="test", is_superuser=True, is_staff=True)
        self.account = KingdeeAccount.objects.create(
            name="Test Account",
            server_url="http://example.invalid/k3cloud",
            acct_id="test",
            username="test",
            app_id="test",
            app_secret="not-a-real-secret",
        )
        KingdeeOrgBinding.objects.create(company=self.company, account=self.account, org_number="001", org_name="Org")
        login_with_company(self.client, self.user, self.company)
        self.folder = tempfile.TemporaryDirectory(prefix="erp-analysis-tests-")
        self.addCleanup(self.folder.cleanup)
        self.storage = override_settings(
            BASE_DIR=Path(self.folder.name), PUBLIC_BASE_URL="https://reports.example.invalid"
        )
        self.storage.enable()
        self.addCleanup(self.storage.disable)

    def task(self, kinds=None, **kwargs):
        return enqueue(self.company, date(2026, 5, 1), kinds or ["purchase"], actor=self.user, **kwargs)

    def test_index_contains_catalog_and_navigation(self):
        response = self.client.get(reverse("reports:erp_analysis"))
        self.assertEqual(response.status_code, 200)
        for kind in REPORT_KINDS.values():
            self.assertContains(response, kind["name"])
        self.assertContains(response, "run_erp_analysis --watch")

    def test_generate_queues_and_requires_post(self):
        url = reverse("reports:erp_analysis_generate")
        self.assertEqual(self.client.get(url).status_code, 405)
        with patch("integrations.services.erp_analysis.runner.build_sdk") as sdk:
            response = self.client.post(url, {"period": "2026-05", "report_kinds": ["purchase", "sales"]})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(sdk.called)
        self.assertEqual(ErpAnalysisTask.objects.get().status, "PENDING")

    def test_invalid_inputs_and_missing_binding(self):
        url = reverse("reports:erp_analysis_generate")
        for period in ("bad", "2999-01"):
            self.assertEqual(self.client.post(url, {"period": period, "report_kinds": ["purchase"]}).status_code, 400)
        self.assertEqual(self.client.post(url, {"period": "2026-05", "report_kinds": ["unknown"]}).status_code, 400)
        KingdeeOrgBinding.objects.filter(company=self.company).update(is_active=False)
        self.assertEqual(self.client.post(url, {"period": "2026-05", "report_kinds": ["purchase"]}).status_code, 400)
        self.assertFalse(ErpAnalysisTask.objects.exists())

    def test_ordinary_business_user_cannot_view_all_company_data(self):
        ordinary = get_user_model().objects.create_user("ordinary")
        login_with_company(self.client, ordinary, self.company)
        self.assertEqual(self.client.get(reverse("reports:erp_analysis")).status_code, 403)
        self.assertEqual(self.client.get(reverse("reports:erp_analysis_status", args=[999])).status_code, 403)
        ordinary.groups.add(Group.objects.get(name="report_viewer"))
        self.assertEqual(self.client.get(reverse("reports:erp_analysis")).status_code, 200)

    def test_other_company_task_is_never_visible(self):
        task = self.task()
        login_with_company(self.client, self.user, self.other)
        for route, args in (
            ("erp_analysis_task", [task.pk]),
            ("erp_analysis_status", [task.pk]),
            ("erp_analysis_download", [task.pk]),
            ("erp_analysis_report", [task.pk, "purchase"]),
        ):
            self.assertEqual(self.client.get(reverse("reports:" + route, args=args)).status_code, 404)

    def test_schedule_idempotent_but_manual_exports_are_not(self):
        first = self.task(deduplication_key="erp-analysis:A:2026-05")
        self.assertEqual(self.task(deduplication_key="erp-analysis:A:2026-05").pk, first.pk)
        self.assertNotEqual(self.task().pk, self.task().pk)

    def test_scheduler_previous_month_once_and_no_default_side_effects(self):
        schedule = ErpAnalysisSchedule.objects.create(
            company=self.company, enabled=False, report_kinds=["purchase"], day=1, hour=8
        )
        now = datetime(2026, 6, 1, 9, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.assertEqual(enqueue_due(now), [])
        schedule.enabled = True
        schedule.save()
        self.assertEqual(enqueue_due(now)[0].period, date(2026, 5, 1))
        enqueue_due(now)
        self.assertEqual(ErpAnalysisTask.objects.count(), 1)

    def test_partial_failure_preserves_good_report_and_manifest(self):
        task = self.task(["purchase", "sales"])
        query = Mock()
        query.organization.return_value = {"id": "100071", "number": "001", "name": "Org"}
        report = serializable(analyze("purchase", SourcesTestsQuery(), query.organization.return_value, task.period, 1))
        with (
            patch("integrations.services.erp_analysis.runner.build_sdk"),
            patch("integrations.services.erp_analysis.runner.AnalysisQuery", return_value=query),
            patch("integrations.services.erp_analysis.runner.analyze", side_effect=[report, ValueError("field error")]),
        ):
            process_task(task.pk)
        task.refresh_from_db()
        self.assertEqual(task.status, "PARTIAL")
        self.assertEqual(task.results["sales"]["error"], "field error")
        with ZipFile(task.bundle_path) as bundle:
            self.assertIn("采购执行分析.html", bundle.namelist())
            self.assertNotIn("销售漏斗分析.html", bundle.namelist())
            self.assertEqual(json.loads(bundle.read("manifest.json"))["reports"]["sales"]["status"], "FAILED")
        self.assertEqual(
            self.client.get(reverse("reports:erp_analysis_report", args=[task.pk, "purchase"])).status_code, 200
        )
        response = self.client.get(reverse("reports:erp_analysis_download", args=[task.pk]))
        self.assertEqual(response.status_code, 200)
        response.close()
        self.assertIsNone(process_task(task.pk))

    def test_login_failure_and_all_reports_failure_are_not_success(self):
        task = self.task()
        with patch("integrations.services.erp_analysis.runner.build_sdk", side_effect=ValueError("login failure")):
            process_task(task.pk)
        task.refresh_from_db()
        self.assertEqual(task.status, "FAILED")
        task = self.task()
        with (
            patch("integrations.services.erp_analysis.runner.build_sdk"),
            patch("integrations.services.erp_analysis.runner.AnalysisQuery") as query,
            patch("integrations.services.erp_analysis.runner.analyze", side_effect=ModuleUnavailable("未购买")),
        ):
            query.return_value.organization.return_value = {"id": "100071", "number": "001", "name": "Org"}
            process_task(task.pk)
        task.refresh_from_db()
        self.assertEqual(task.status, "FAILED")
        self.assertEqual(task.results["purchase"]["status"], "SKIPPED")

    def test_html_escapes_erp_content(self):
        task = self.task()
        query = SourcesTestsQuery()
        data = analyze("purchase", query, {"id": "100071", "number": "001", "name": "Org"}, task.period, 1)
        data["notes"].append('<script>alert("erp")</script>')
        task.results = {"purchase": {"status": "SUCCESS", "report": serializable(data)}}
        task.save()
        response = self.client.get(reverse("reports:erp_analysis_report", args=[task.pk, "purchase"]))
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, '<script>alert("erp")</script>')

    def test_notification_failure_does_not_change_report_status_or_regenerate(self):
        app = DingtalkApp.objects.create(company=self.company, app_key="test", app_secret="test", robot_code="test")
        group = DingtalkGroupConfig.objects.create(
            company=self.company, app=app, name="Test", open_conversation_id="test", send_at=time(8)
        )
        task = self.task(notification_group=group)
        task.status = "SUCCESS"
        task.save()
        with patch("integrations.services.erp_analysis.runner.DingtalkClient") as client:
            client.return_value.post.side_effect = ValueError("notification failure")
            notify(task.pk)
        task.refresh_from_db()
        self.assertEqual(task.status, "SUCCESS")
        self.assertEqual(task.notification_status, "FAILED")
        with patch("integrations.services.erp_analysis.runner.DingtalkClient") as client:
            notify(task.pk)
            self.assertFalse(client.called)
            notify(task.pk, retry=True)
            self.assertEqual(client.return_value.post.call_count, 1)
        task.refresh_from_db()
        self.assertEqual(task.notification_status, "SENT")
        with patch("integrations.services.erp_analysis.runner.DingtalkClient") as client:
            notify(task.pk, retry=True)
            self.assertFalse(client.called)

    def test_group_company_unchecked_blocks_notification(self):
        app = DingtalkApp.objects.create(company=self.company, app_key="test", app_secret="test", robot_code="test")
        group = DingtalkGroupConfig.objects.create(
            company=self.company, app=app, name="Test", open_conversation_id="test", send_at=time(8)
        )
        group.companies.add(self.other)
        task = self.task(notification_group=group)
        task.status = "SUCCESS"
        task.save()
        with patch("integrations.services.erp_analysis.runner.DingtalkClient") as client:
            notify(task.pk)
        self.assertFalse(client.called)
        task.refresh_from_db()
        self.assertEqual(task.notification_status, "FAILED")

    def test_recover_only_reruns_unfinished_reports(self):
        task = self.task(["purchase", "sales"])
        org = {"id": "100071", "number": "001", "name": "Org"}
        task.status = "RUNNING"
        task.results = {
            "purchase": {
                "status": "SUCCESS",
                "report": serializable(analyze("purchase", SourcesTestsQuery(), org, task.period, 1)),
            }
        }
        task.save()
        data = analyze("sales", SourcesTestsQuery(), org, task.period, 1)
        with (
            patch("integrations.services.erp_analysis.runner.build_sdk"),
            patch("integrations.services.erp_analysis.runner.AnalysisQuery") as query,
            patch("integrations.services.erp_analysis.runner.analyze", return_value=data) as analyzer,
        ):
            query.return_value.organization.return_value = org
            call_command("run_erp_analysis", recover_task=task.pk)
        self.assertEqual(analyzer.call_count, 1)
        self.assertEqual(analyzer.call_args.args[0], "sales")
        task.refresh_from_db()
        self.assertEqual(task.status, "SUCCESS")

    def test_finished_pending_notification_is_checked_after_restart(self):
        task = self.task()
        task.status = "SUCCESS"
        task.notification_status = "PENDING"
        task.save()
        with patch("integrations.management.commands.run_erp_analysis.notify") as notifier:
            call_command("run_erp_analysis")
        notifier.assert_called_once_with(task.pk)

    def test_schedule_admin_has_checkbox_kinds(self):
        response = self.client.get("/admin/integrations/erpanalysisschedule/add/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="report_kinds"')
        self.assertContains(response, "采购执行分析")

    def test_single_month_task_is_persisted_and_passed_to_analyzer(self):
        task = enqueue(self.company, date(2026, 10, 1), ["purchase"], window_months=1)
        data = analyze(
            "purchase", SourcesTestsQuery(), {"id": "100071", "number": "001", "name": "Org"}, task.period, 1
        )
        with (
            patch("integrations.services.erp_analysis.runner.build_sdk"),
            patch("integrations.services.erp_analysis.runner.AnalysisQuery") as query,
            patch("integrations.services.erp_analysis.runner.analyze", return_value=data) as analyzer,
        ):
            query.return_value.organization.return_value = {"id": "100071", "number": "001", "name": "Org"}
            process_task(task.pk)
        self.assertEqual(analyzer.call_args.args[-1], 1)
        task.refresh_from_db()
        self.assertEqual(task.results["purchase"]["report"]["window"], "2026-10-01 ~ 2026-10-31")

    def test_signed_public_snapshot_and_download_require_matching_valid_token(self):
        task = self.task()
        data = analyze(
            "purchase", SourcesTestsQuery(), {"id": "100071", "number": "001", "name": "Org"}, task.period, 1
        )
        task.results = {"purchase": {"status": "SUCCESS", "report": serializable(data)}}
        task.status = "SUCCESS"
        from integrations.services.erp_analysis.runner import archive

        task.bundle_path = archive(task)
        task.save()
        self.client.logout()
        url = reverse("reports:erp_analysis_public", args=[task.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.get(url, {"token": "bad"}).status_code, 403)
        token = snapshot_token(task)
        response = self.client.get(url, {"token": token})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ZIP 分析包")
        self.assertContains(response, "订单执行、结算、交付分布与供应商集中度")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        report_url = reverse("reports:erp_analysis_public_report", args=[task.pk, "purchase"])
        self.assertEqual(self.client.get(report_url, {"token": token}).status_code, 200)
        self.assertEqual(
            self.client.get(
                reverse("reports:erp_analysis_public_report", args=[task.pk, "sales"]), {"token": token}
            ).status_code,
            404,
        )
        download = self.client.get(url, {"token": token, "download": "zip"})
        self.assertEqual(download.status_code, 200)
        download.close()
        other = self.task()
        self.assertEqual(
            self.client.get(reverse("reports:erp_analysis_public", args=[other.pk]), {"token": token}).status_code, 403
        )
        wrong_company = signing.dumps({"task": task.pk, "company": self.other.pk}, salt=SNAPSHOT_SALT)
        self.assertEqual(self.client.get(url, {"token": wrong_company}).status_code, 404)
        with patch("django.core.signing.time.time", return_value=0):
            expired = snapshot_token(task)
        self.assertEqual(self.client.get(url, {"token": expired}).status_code, 403)

    def test_notification_names_zip_and_each_analysis_content(self):
        app = DingtalkApp.objects.create(company=self.company, app_key="test", app_secret="test", robot_code="test")
        group = DingtalkGroupConfig.objects.create(
            company=self.company, app=app, name="Test", open_conversation_id="test", send_at=time(8)
        )
        task = self.task(["purchase", "sales"], notification_group=group)
        task.status = "PARTIAL"
        task.results = {"purchase": {"status": "SUCCESS"}, "sales": {"status": "FAILED"}}
        task.save()
        with patch("integrations.services.erp_analysis.runner.DingtalkClient") as client:
            notify(task.pk)
        payload = json.loads(client.return_value.post.call_args.args[1]["msgParam"])
        self.assertIn("ZIP", payload["title"])
        self.assertIn(".zip", payload["text"])
        self.assertIn("采购执行分析（已生成）", payload["text"])
        self.assertIn("销售漏斗分析（失败）", payload["text"])
        self.assertIn(REPORT_KINDS["purchase"]["description"], payload["text"])
        self.assertIn("/public/?token=", payload["messageUrl"])


class SourcesTestsQuery:
    def bill(self, *args):
        return []

    def report(self, *args):
        return []
