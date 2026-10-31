"""经营日报 A2UI 与 PDF/Excel 三件套投递回归。"""
import copy
import json
from datetime import date, datetime, time
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
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


class A2UITemplateContractTests(SimpleTestCase):
    def test_chart_sizing_matches_public_catalog_enum(self):
        for name in ("operations_daily_report", "payment_application_report"):
            frames = json.loads(
                (Path(__file__).resolve().parents[2] / f"docs/templates/{name}.a2ui.json").read_text(encoding="utf-8")
            )
            components = next(f["updateComponents"]["components"] for f in frames if "updateComponents" in f)
            for component in components:
                if component["component"] != "Chart":
                    continue
                if "aspectRatio" in component:
                    self.assertIn(component["aspectRatio"], {"1:1", "2:1", "4:3", "16:9"}, name)
                    self.assertNotIn("height", component, name)
                else:
                    self.assertGreater(component.get("height", 0), 0, name)


class MetricsImageTests(SimpleTestCase):
    def test_three_scopes_render_into_single_image(self):
        from integrations.services.operations_a2ui import build_operations_model
        from integrations.services.operations_metrics_image import metrics_cells, render_metrics_html
        model = build_operations_model(fake_snapshot())
        headers, rows = metrics_cells(model)
        self.assertEqual(headers, ["采购", "销售", "占比"])
        self.assertEqual([row[0] for row in rows], ["当月累计", "人员日报", "金蝶 K3Cloud"])
        self.assertEqual(rows[0][1], ["4.00", "5.00", "80.0%"])
        html = render_metrics_html(model)
        self.assertIn("4.00", html)
        self.assertIn("金蝶 K3Cloud", html)
        self.assertIn("单位：万元", html)

    def test_metrics_image_reference_is_bound_when_available(self):
        frames = build_operations_a2ui_messages(
            fake_snapshot(), metrics_image={"light": "@lAD-light"}
        )
        model = frames[1]["updateDataModel"]["value"]
        self.assertTrue(model["hasMetricsImage"])
        components = next(f["updateComponents"]["components"] for f in frames if "updateComponents" in f)
        image = next(c for c in components if c["id"] == "metrics-image")
        self.assertEqual(image["component"], "ImageList")
        self.assertEqual(image["images"], ["@lAD-light"])


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
        self.assertEqual(model['summary']['reportSalesDailyText'],'¥10,000.00')
        self.assertEqual(model['summary']['reportPurchaseDailyText'],'¥8,000.00')
        self.assertEqual(model['summary']['k3ShareDailyText'],'80.0%')
        self.assertEqual(model['charts']['kingdeeShare']['type'],'pieChart')
        self.assertTrue(model['hasReportShare'])
        self.assertEqual(len({next(v for k,v in f.items() if k!='version')['surfaceId'] for f in frames}),1)
        self.assertNotEqual(frames[0]['createSurface']['surfaceId'],build_operations_a2ui_messages(fake_snapshot())[0]['createSurface']['surfaceId'])

    def test_missing_manual_daily_is_not_backfilled_with_kingdee(self):
        snapshot=fake_snapshot()
        snapshot.data['sales'].pop('daily_coverage')
        model=build_operations_a2ui_messages(snapshot)[1]['updateDataModel']['value']
        self.assertEqual(model['summary']['reportSalesDailyText'],'—')
        self.assertEqual(model['summary']['reportShareDailyText'],'—')
        self.assertFalse(model['hasReportShare'])
        self.assertTrue(model['hasKingdeeShare'])

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
        self.assertEqual(model['summary']['salesDailyText'],'—')
        self.assertEqual(model['summary']['reportSalesDailyText'],'¥999.00')
        self.assertEqual(model['summary']['reportShareDailyText'],'—')

    def test_non_finite_amounts_are_rejected(self):
        snapshot=fake_snapshot();snapshot.data['operations']['sales_total']=float('inf')
        with self.assertRaises(ValueError):build_operations_a2ui_messages(snapshot)

    def test_report_link_is_optional_and_hidden_without_url(self):
        frames=build_operations_a2ui_messages(fake_snapshot(), link_url="http://host/snapshots/1/public/?token=x")
        components=next(f["updateComponents"]["components"] for f in frames if "updateComponents" in f)
        link=next(c for c in components if c["id"]=="report-link")
        self.assertEqual(link["content"],"[查看完整在线报表（含图表与明细）](http://host/snapshots/1/public/?token=x)")
        self.assertNotIn("visible",link)
        hidden=build_operations_a2ui_messages(fake_snapshot())
        components=next(f["updateComponents"]["components"] for f in hidden if "updateComponents" in f)
        self.assertIs(next(c for c in components if c["id"]=="report-link")["visible"],False)


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
        # 这些用例验证的是投递阶段本身，配置视为早已启用。
        DingtalkGroupConfig.objects.filter(pk=self.group.pk).update(
            enabled_at=timezone.make_aware(datetime(2026, 1, 1))
        )
        self.group.refresh_from_db()  # 同步内存值，避免后续 save() 用旧值覆盖基线
        self.snapshot = ReportSnapshot.objects.create(company=self.company, report_date=date(2026, 10, 27),
                                                      scope="BOTH", data=fixture_data(), is_complete=True)
        self.client_mock = Mock()
        self.client_mock.app = self.app
        self.client_mock.upload_media.side_effect = lambda name, data, media_type="file": "media-image"
        self.client_mock.post.side_effect = success_response
        self.patches = [
            patch("integrations.services.dingtalk_client.build_client", return_value=self.client_mock),
            patch("integrations.services.operations_delivery.render_metrics_image",
                  return_value=bytes([137, 80, 78, 71]) + b"-test"),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def send(self):
        return _send_to_dingtalk_channels(self.snapshot, send_now=True)

    def delivery(self):
        return ReportDelivery.objects.get(snapshot=self.snapshot, channel="DINGTALK")

    def test_card_is_the_only_message_and_is_not_duplicated(self):
        self.assertEqual(self.send()[0][1], "SENT")
        calls = self.client_mock.post.call_args_list
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].args[0].endswith("createAndDeliver"))
        self.assertEqual(calls[0].args[1]["imGroupOpenDeliverModel"], {"robotCode": "robot-code"})
        state = self.delivery().delivery_state
        self.assertEqual(state["card"]["status"], "SENT")
        for key in ("link", "pdf", "excel"):
            self.assertNotIn(key, state)
        self.assertFalse(state["inProgress"])
        self.assertEqual(self.send()[0][1], "SKIPPED")
        self.assertEqual(self.client_mock.post.call_count, 1)

    def test_card_carries_snapshot_link_without_a_separate_link_message(self):
        self.assertEqual(self.send()[0][1], "SENT")
        payload = self.client_mock.post.call_args.args[1]
        self.assertNotIn("msgKey", payload)  # 只有卡片，没有 sampleLink/sampleFile
        frames = json.loads(payload["a2uiMessages"][2])
        link = next(c for c in frames["updateComponents"]["components"] if c["id"] == "report-link")
        self.assertEqual(link["component"], "Markdown")
        self.assertIn("/snapshots/", link["content"])
        self.assertNotIn("visible", link)

    def test_metrics_image_failure_falls_back_to_text_card(self):
        self.client_mock.upload_media.side_effect = RuntimeError("upload failed")
        self.assertEqual(self.send()[0][1], "SENT")
        self.assertEqual(self.client_mock.post.call_count, 1)
        model = json.loads(
            self.client_mock.post.call_args.args[1]["a2uiMessages"][1]
        )["updateDataModel"]["value"]
        self.assertFalse(model["hasMetricsImage"])

    def test_sales_only_filter_applies_to_card(self):
        self.group.content_types = ["SALES"]
        self.group.save()
        self.assertEqual(self.send()[0][1], "SENT")
        payload = self.client_mock.post.call_args.args[1]
        model = json.loads(payload["a2uiMessages"][1])["updateDataModel"]["value"]
        self.assertEqual({row["type"] for row in model["charts"]["month"]["data"]}, {"销售"})
        self.snapshot.refresh_from_db()
        self.assertIn("purchase", self.snapshot.data)

    def test_approval_only_group_does_not_receive_operations_snapshot(self):
        self.group.content_types = ["APPROVALS"]
        self.group.save()
        self.assertEqual(self.send(), [])
        self.client_mock.post.assert_not_called()
        self.assertFalse(ReportDelivery.objects.exists())

    def test_unselected_company_does_not_receive_card(self):
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

    def test_fixed_robot_configuration_can_retry_safely(self):
        self.app.robot_code = ""
        self.assertEqual(self.send()[0][1], "FAILED")
        self.app.robot_code = "robot-code"
        self.assertEqual(self.send()[0][1], "SENT")
        self.assertEqual(self.client_mock.post.call_count, 1)

    def test_card_timeout_is_uncertain_and_never_automatically_resent(self):
        self.client_mock.post.side_effect = TimeoutError("network timeout")
        self.assertEqual(self.send()[0][1], "UNCERTAIN")
        state = self.delivery().delivery_state
        self.assertEqual(state["card"]["status"], "UNCERTAIN")
        self.assertTrue(Path(state["card"]["receiptPath"]).exists())
        self.assertEqual(self.send()[0][1], "SKIPPED")
        self.client_mock.post.assert_called_once()

    def test_changed_snapshot_after_failure_requires_manual_check(self):
        self.app.robot_code = ""
        self.assertEqual(self.send()[0][1], "FAILED")
        self.snapshot.data["sales"]["daily_coverage"]["total_amount"] = 999
        self.snapshot.save()
        self.app.robot_code = "robot-code"
        self.assertEqual(self.send()[0][1], "UNCERTAIN")
        self.client_mock.post.assert_not_called()

    def test_business_selection_changed_after_failure_is_not_mixed(self):
        self.app.robot_code = ""
        self.assertEqual(self.send()[0][1], "FAILED")
        self.group.content_types = ["PURCHASE"]
        self.group.save()
        self.app.robot_code = "robot-code"
        self.assertEqual(self.send()[0][1], "UNCERTAIN")
        self.client_mock.post.assert_not_called()

    def test_changed_group_id_after_failure_is_not_mixed(self):
        self.app.robot_code = ""
        self.assertEqual(self.send()[0][1], "FAILED")
        self.group.open_conversation_id = "cid-other"
        self.group.save()
        self.app.robot_code = "robot-code"
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
        workbook = load_workbook(BytesIO(export_snapshot_to_excel(filtered)))
        self.assertTrue(any("采购" in name for name in workbook.sheetnames))
        self.assertFalse(any("销售" in name for name in workbook.sheetnames))

    def test_book_html_respects_purchase_selection(self):
        from integrations.services.report_delivery import render_snapshot_book_html
        selected = filter_snapshot_for_contents(self.snapshot, ["PURCHASE"])
        html = render_snapshot_book_html(selected)
        self.assertIn("当月采购日报合计", html)
        self.assertNotIn("当月销售日报合计", html)
