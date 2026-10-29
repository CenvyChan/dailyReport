"""经营日报 A2UI 与 PDF/Excel 三件套投递回归。"""
import copy
import json
from datetime import date, time
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, TestCase, override_settings
from openpyxl import load_workbook

from core.testing import company_a
from integrations.models import DingtalkApp, DingtalkGroupConfig, ReportDelivery, ReportSnapshot
from integrations.services.operations_a2ui import build_operations_a2ui_messages, filter_snapshot_for_contents
from integrations.services.report_delivery import _send_to_dingtalk_channels


def fixture_data():
    def business(amount, name):
        return {
            "daily_coverage": {"total_reports": 2, "total_amount": amount, "covered_amount": 4000,
                               "coverage_rate": 40.0 if amount else None,
                               "details": [{"party_name": name, "amount": amount}]},
            "daily_trend": {"points": [{"date": "2026-10-26", "value": -2000},
                                         {"date": "2026-10-27", "value": amount}]},
            "month_diff": {"system_amount": 50000, "k3_amount": 48000, "diff_amount": 2000,
                           "diff_rate": 4.1667},
            "year_diff": {"diff_amount": -3000}, "k3_allocation": {"details": []},
        }
    return {"operations":{"source":"KINGDEE","period_start":"2026-10-01","period_end":"2026-10-27","trend_start":"2026-10-13",
                          "sales_total":"50000","purchase_total":"40000","share_total":"80","sales_daily":"10000","purchase_daily":"8000",
                          "month_rows":[{"date":"2026-10-26","sales_amount":"-2000","purchase_amount":"-1000"},{"date":"2026-10-27","sales_amount":"10000","purchase_amount":"8000"}],
                          "trend_rows":[{"date":"2026-10-26","sales_amount":"-2000","purchase_amount":"-1000"},{"date":"2026-10-27","sales_amount":"10000","purchase_amount":"8000"}]},
            "monthly_comparison":{"source":"MANUAL_REPORTS","year":2026,"month":10,"sales_total":"50000","purchase_total":"40000","share_total":"80","rows":[]},
            "sales": business(10000, "销售对象"), "purchase": business(8000, "采购对象"),
            "corrections": [{"affected_report": "销售", "reason": "销售更正"},
                            {"affected_report": "采购", "reason": "采购更正"}]}


def fake_snapshot():
    return SimpleNamespace(pk=9, company_id=1, company=SimpleNamespace(name="卡片示例公司", code="DEMO"),
                           scope="BOTH", report_date=date(2026, 10, 27), data=fixture_data(),
                           is_complete=True, sync_warnings=[], calculation_version="test")


def success_response(path, payload):
    if path.endswith("createAndDeliver"):
        return {"success": True, "result": {"outTrackId": payload["outTrackId"], "deliverResults": [
            {"spaceId": payload["openSpaceId"].split("IM_GROUP.", 1)[1], "spaceType": "IM_GROUP", "success": True}
        ]}}
    return {"processQueryKey": "accepted"}


class OperationsA2UIModelTests(SimpleTestCase):
    def test_combined_native_chart_and_summary_use_frozen_k3_data(self):
        frames=build_operations_a2ui_messages(fake_snapshot());model=frames[1]['updateDataModel']['value']
        self.assertNotIn('sections',model)
        self.assertEqual(model['summary']['salesDailyText'],'¥10,000.00')
        self.assertEqual(model['summary']['purchaseDailyText'],'¥8,000.00')
        self.assertEqual(model['summary']['shareText'],'80.0%')
        self.assertEqual(model['charts']['trend']['data'][0]['y'],-0.2)
        self.assertNotIn('monthDiffText',model['summary'])
        self.assertNotIn('利润',model['deliverySummary'])
        self.assertEqual(len({next(v for k,v in f.items() if k!='version')['surfaceId'] for f in frames}),1)
        self.assertNotEqual(frames[0]['createSurface']['surfaceId'],build_operations_a2ui_messages(fake_snapshot())[0]['createSurface']['surfaceId'])

    def test_purchase_only_scope_does_not_leak_sales_values(self):
        original=fake_snapshot();selected=filter_snapshot_for_contents(original,['PURCHASE','APPROVALS'])
        model=build_operations_a2ui_messages(selected)[1]['updateDataModel']['value']
        self.assertEqual(selected.scope,'PURCHASE');self.assertNotIn('sales',selected.data)
        self.assertEqual({row['type'] for row in model['charts']['month']['data']},{'采购'})
        self.assertNotIn('salesTotalText',model['summary'])
        self.assertNotIn('sales_total',selected.data['operations'])
        self.assertIn('sales_total',original.data['operations'])
        self.assertIn('sales_amount',original.data['operations']['month_rows'][0])

    def test_empty_scope_is_rejected_and_legacy_missing_values_warn(self):
        with self.assertRaises(ValueError):filter_snapshot_for_contents(fake_snapshot(),['APPROVALS'])
        snapshot=fake_snapshot();snapshot.scope='SALES';snapshot.is_complete=False
        snapshot.data={'sales':{'daily_coverage':{'total_amount':999}}}
        model=build_operations_a2ui_messages(snapshot)[1]['updateDataModel']['value']
        self.assertEqual(model['charts']['trend']['data'],[])
        self.assertTrue(model['hasWarnings']);self.assertIn('历史快照',model['warningText'])
        self.assertNotIn('999',json.dumps(model))

    def test_non_finite_amounts_are_rejected(self):
        snapshot=fake_snapshot();snapshot.data['operations']['sales_total']=float('inf')
        with self.assertRaises(ValueError):build_operations_a2ui_messages(snapshot)


class OperationsA2UIDeliveryTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = override_settings(BASE_DIR=Path(self.directory.name))
        self.settings.enable()
        self.addCleanup(self.settings.disable)
        self.company = company_a()
        self.app = DingtalkApp.objects.create(company=self.company, name="日报机器人", app_key="app-key",
                                             app_secret="secret", robot_code="robot-code")
        self.group = DingtalkGroupConfig.objects.create(company=self.company, app=self.app, name="日报群",
                                                        open_conversation_id="cid-test", send_at=time(18),
                                                        content_types=["SALES", "PURCHASE"])
        self.group.companies.set([self.company])
        self.snapshot = ReportSnapshot.objects.create(company=self.company, report_date=date(2026, 10, 27),
                                                      scope="BOTH", data=fixture_data(), is_complete=True)
        self.client_mock = Mock()
        self.client_mock.app = self.app
        self.client_mock.upload_media.side_effect = lambda name, data: "media-" + Path(name).suffix
        self.client_mock.post.side_effect = success_response
        self.pdf = Mock(return_value=b"%PDF-test")
        self.excel = Mock(return_value=b"PK-test")
        self.patches = [
            patch("integrations.services.dingtalk_client.build_client", return_value=self.client_mock),
            patch("integrations.services.report_delivery.render_snapshot_pdf", self.pdf),
            patch("integrations.services.snapshot_export.export_snapshot_to_excel", self.excel),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def send(self):
        return _send_to_dingtalk_channels(self.snapshot, send_now=True)

    def delivery(self):
        return ReportDelivery.objects.get(snapshot=self.snapshot, channel="DINGTALK")

    def test_three_deliveries_use_robot_identity_and_are_not_duplicated(self):
        self.assertEqual(self.send()[0][1], "SENT")
        calls = self.client_mock.post.call_args_list
        self.assertEqual(len(calls), 3)
        self.assertTrue(calls[0].args[0].endswith("createAndDeliver"))
        self.assertEqual(calls[0].args[1]["imGroupOpenDeliverModel"], {"robotCode": "robot-code"})
        filenames = [json.loads(c.args[1]["msgParam"])["fileName"] for c in calls[1:]]
        self.assertTrue(filenames[0].endswith(".pdf"))
        self.assertTrue(filenames[1].endswith(".xlsx"))
        self.assertTrue(all(c.args[1]["robotCode"] == "robot-code" for c in calls[1:]))
        state = self.delivery().delivery_state
        self.assertEqual([state[k]["status"] for k in ("card", "pdf", "excel")], ["SENT"] * 3)
        self.assertFalse(state["inProgress"])
        self.assertEqual(self.send()[0][1], "SKIPPED")
        self.assertEqual(self.client_mock.post.call_count, 3)

    def test_pdf_failure_prevents_partial_card_and_can_retry(self):
        self.pdf.side_effect = RuntimeError("Chromium unavailable")
        self.assertEqual(self.send()[0][1], "FAILED")
        self.client_mock.post.assert_not_called()
        self.client_mock.upload_media.assert_not_called()
        self.pdf.side_effect = None
        self.assertEqual(self.send()[0][1], "SENT")
        self.assertEqual(self.client_mock.post.call_count, 3)

    def test_upload_failure_is_retryable_without_duplicate_group_messages(self):
        self.client_mock.upload_media.side_effect = RuntimeError("upload failed")
        self.assertEqual(self.send()[0][1], "FAILED")
        self.client_mock.post.assert_not_called()
        self.client_mock.upload_media.side_effect = lambda name, data: "media-" + Path(name).suffix
        self.assertEqual(self.send()[0][1], "SENT")
        self.assertEqual(self.client_mock.post.call_count, 3)

    def test_card_timeout_is_uncertain_and_never_automatically_resent(self):
        self.client_mock.post.side_effect = TimeoutError("network timeout")
        self.assertEqual(self.send()[0][1], "UNCERTAIN")
        state = self.delivery().delivery_state
        self.assertEqual(state["card"]["status"], "UNCERTAIN")
        self.assertTrue(Path(state["card"]["receiptPath"]).exists())
        self.assertEqual(self.send()[0][1], "SKIPPED")
        self.client_mock.post.assert_called_once()

    def test_excel_timeout_does_not_resend_successful_card_or_pdf(self):
        def responder(path, payload):
            if payload.get("msgKey") == "sampleFile" and json.loads(payload["msgParam"])["fileName"].endswith(".xlsx"):
                raise TimeoutError("excel outcome unknown")
            return success_response(path, payload)
        self.client_mock.post.side_effect = responder
        self.assertEqual(self.send()[0][1], "UNCERTAIN")
        state = self.delivery().delivery_state
        self.assertEqual(state["card"]["status"], "SENT")
        self.assertEqual(state["pdf"]["status"], "SENT")
        self.assertEqual(state["excel"]["status"], "UNCERTAIN")
        self.assertEqual(self.send()[0][1], "SKIPPED")
        self.assertEqual(self.client_mock.post.call_count, 3)

    def test_manual_resolution_resumes_only_missing_excel(self):
        def responder(path, payload):
            if payload.get("msgKey") == "sampleFile" and json.loads(payload["msgParam"])["fileName"].endswith(".xlsx"):
                raise TimeoutError("excel outcome unknown")
            return success_response(path, payload)
        self.client_mock.post.side_effect = responder
        self.assertEqual(self.send()[0][1], "UNCERTAIN")
        d = self.delivery()
        d.delivery_state["excel"]["status"] = "READY"  # 运维已核对群里确实没有附件。
        d.status = "FAILED"
        d.save()
        card_path = Path(d.delivery_state["card"]["receiptPath"]).with_name("card.a2ui.json")
        original_card = card_path.read_bytes()
        self.client_mock.post.side_effect = success_response
        self.assertEqual(self.send()[0][1], "SENT")
        self.assertEqual(card_path.read_bytes(), original_card)
        self.assertEqual(self.client_mock.post.call_count, 4)
        self.assertTrue(json.loads(self.client_mock.post.call_args.args[1]["msgParam"])["fileName"].endswith(".xlsx"))

    def test_sales_only_filter_applies_to_card_pdf_and_excel(self):
        self.group.content_types = ["SALES"]
        self.group.save()
        self.assertEqual(self.send()[0][1], "SENT")
        for renderer in (self.pdf, self.excel):
            argument = renderer.call_args.args[0]
            self.assertEqual(argument.scope, "SALES")
            self.assertNotIn("purchase", argument.data)
            self.assertEqual(len(argument.data["corrections"]), 1)
        payload = self.client_mock.post.call_args_list[0].args[1]
        model = json.loads(payload["a2uiMessages"][1])["updateDataModel"]["value"]
        self.assertEqual({row['type'] for row in model['charts']['month']['data']}, {'销售'})
        self.snapshot.refresh_from_db()
        self.assertIn("purchase", self.snapshot.data)

    def test_approval_only_group_does_not_receive_operations_snapshot(self):
        self.group.content_types = ["APPROVALS"]
        self.group.save()
        self.assertEqual(self.send(), [])
        self.client_mock.post.assert_not_called()
        self.assertFalse(ReportDelivery.objects.exists())

    def test_unselected_company_does_not_receive_card_or_attachments(self):
        from core.models import Company
        other = Company.objects.create(code="OPS-OTHER", name="其他公司")
        self.group.companies.set([other])
        self.assertEqual(self.send(), [])
        self.client_mock.post.assert_not_called()

    def test_missing_robot_code_fails_before_upload(self):
        self.app.robot_code = ""
        self.client_mock.app = self.app
        self.assertEqual(self.send()[0][1], "FAILED")
        self.client_mock.upload_media.assert_not_called()
        self.client_mock.post.assert_not_called()

    def test_changed_snapshot_after_failure_requires_manual_check(self):
        self.pdf.side_effect = RuntimeError("render failed")
        self.assertEqual(self.send()[0][1], "FAILED")
        self.snapshot.data["sales"]["daily_coverage"]["total_amount"] = 999
        self.snapshot.save()
        self.pdf.side_effect = None
        self.assertEqual(self.send()[0][1], "UNCERTAIN")
        self.client_mock.post.assert_not_called()

    def test_existing_sending_checkpoint_is_not_reissued(self):
        ReportDelivery.objects.create(snapshot=self.snapshot, channel="DINGTALK",
                                      target_identifier=str(self.group.pk), delivery_state={"inProgress": True})
        self.assertEqual(self.send()[0][1], "UNCERTAIN")
        self.client_mock.post.assert_not_called()

    def test_existing_legacy_failure_is_not_blindly_reissued(self):
        ReportDelivery.objects.create(snapshot=self.snapshot, channel="DINGTALK",
                                      target_identifier=str(self.group.pk), status="FAILED", attempt_count=1)
        self.assertEqual(self.send()[0][1], "UNCERTAIN")
        self.client_mock.post.assert_not_called()

    def test_real_excel_contains_only_selected_business(self):
        from integrations.services.snapshot_export import export_snapshot_to_excel
        filtered = filter_snapshot_for_contents(self.snapshot, ["PURCHASE"])
        # 原始导出器，不使用测试 mock。
        self.patches[-1].stop()
        from integrations.services.snapshot_export import export_snapshot_to_excel
        workbook = load_workbook(BytesIO(export_snapshot_to_excel(filtered)))
        self.assertTrue(any("采购" in name for name in workbook.sheetnames))
        self.assertFalse(any("销售" in name for name in workbook.sheetnames))

    def test_fixed_robot_configuration_can_retry_safely(self):
        self.app.robot_code = ""
        self.assertEqual(self.send()[0][1], "FAILED")
        self.app.robot_code = "robot-code"
        self.assertEqual(self.send()[0][1], "SENT")
        self.assertEqual(self.client_mock.post.call_count, 3)

    def test_invalid_pdf_is_not_sent_or_replaced_with_html(self):
        self.pdf.return_value = b"<html>error</html>"
        self.assertEqual(self.send()[0][1], "FAILED")
        self.client_mock.post.assert_not_called()
        self.client_mock.upload_media.assert_not_called()

    def test_invalid_excel_is_not_sent(self):
        self.excel.return_value = b"not-an-excel"
        self.assertEqual(self.send()[0][1], "FAILED")
        self.client_mock.post.assert_not_called()
        self.client_mock.upload_media.assert_not_called()

    def test_pdf_contents_and_excel_both_respect_purchase_selection(self):
        from integrations.services.report_delivery import render_snapshot_book_html
        selected = filter_snapshot_for_contents(self.snapshot, ["PURCHASE"])
        html = render_snapshot_book_html(selected)
        self.assertIn("当月采购日报合计", html)
        self.assertNotIn("当月销售日报合计", html)

    def test_business_selection_changed_after_failure_is_not_mixed(self):
        self.pdf.side_effect = RuntimeError("render failed")
        self.assertEqual(self.send()[0][1], "FAILED")
        self.group.content_types = ["PURCHASE"]
        self.group.save()
        self.pdf.side_effect = None
        self.assertEqual(self.send()[0][1], "UNCERTAIN")
        self.client_mock.post.assert_not_called()

    def test_changed_group_id_after_failure_is_not_mixed(self):
        self.pdf.side_effect = RuntimeError("render failed")
        self.assertEqual(self.send()[0][1], "FAILED")
        self.group.open_conversation_id = "cid-other"
        self.group.save()
        self.pdf.side_effect = None
        self.assertEqual(self.send()[0][1], "UNCERTAIN")
        self.client_mock.post.assert_not_called()
