import json
import subprocess
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from django.test import SimpleTestCase

from integrations.services.dingtalk_client import DingtalkError
from integrations.services.payment_a2ui import (
    DingtalkA2UIClient,
    build_payment_a2ui_messages,
)
from integrations.services.payment_report import get_last_month_range, get_last_week_range


def report_data():
    return {
        "summary": {"total_count": 4, "total_amount": Decimal("375.00")},
        "by_recipient": [
            {
                "recipient": "收款人甲", "count": 2, "amount": Decimal("300"),
                "details": [
                    {"create_date": "2026-10-19", "amount": Decimal("100"), "status": "COMPLETED"},
                    {"create_date": "2026-10-21", "amount": Decimal("200"), "status": "RUNNING"},
                ],
            },
            {
                "recipient": "收款人乙", "count": 1, "amount": Decimal("50"),
                "details": [{"create_date": "2026-10-25", "amount": Decimal("50"), "status": "TERMINATED"}],
            },
            {
                "recipient": "收款人丙", "count": 1, "amount": Decimal("25"),
                "details": [{"create_date": "2026-10-25", "amount": Decimal("25"), "status": "NEW"}],
            },
        ],
    }


def messages():
    return build_payment_a2ui_messages(
        report_data(), get_last_week_range(date(2026, 10, 27)), "测试公司", "week"
    )


class PaymentA2UIDataTests(SimpleTestCase):
    def test_card_labels_total_as_period_initiated_flows(self):
        template_path = Path(__file__).resolve().parents[2] / "docs" / "templates" / "payment_application_report.a2ui.json"
        template = json.loads(template_path.read_text(encoding="utf-8"))
        components = template[2]["updateComponents"]["components"]
        count_label = next(item["text"] for item in components if item.get("id") == "count-label")
        self.assertEqual(count_label, "本期发起流程数")

    def test_real_amounts_statuses_and_charts_agree(self):
        frames = messages()
        model = frames[1]["updateDataModel"]["value"]
        self.assertEqual(model["companyName"], "测试公司")
        self.assertEqual(model["reportMeta"]["dataMode"], "live")
        self.assertEqual(model["summary"]["totalCount"], 4)
        self.assertEqual(model["summary"]["totalAmountText"], "¥375.00")
        self.assertEqual(model["summary"]["averageAmountText"], "¥93.75")
        self.assertEqual(model["summary"]["completionRateText"], "25.0%")
        amounts = {row["status"]: row["amount"] for row in model["statusBreakdown"]}
        self.assertEqual(amounts, {"COMPLETED": 100, "RUNNING": 200, "TERMINATED": 50, "NEW": 25})
        self.assertEqual(sum(row["count"] for row in model["dailyApplications"]), 4)
        self.assertEqual(len(model["dailyApplications"]), 7)
        self.assertEqual(model["dailyApplications"][1]["amount"], 0)
        for chart in model["charts"].values():
            self.assertAlmostEqual(sum(point["y"] for point in chart["data"]), 0.0375)
        self.assertNotIn("演示", json.dumps(frames, ensure_ascii=False))
        self.assertNotIn("较上期", model["summary"]["amountChangeText"])
        self.assertEqual(len({next(v for k, v in f.items() if k != "version")["surfaceId"] for f in frames}), 1)
        self.assertNotEqual(frames[0]["createSurface"]["surfaceId"], messages()[0]["createSurface"]["surfaceId"])
        components = frames[2]["updateComponents"]["components"]
        self.assertFalse(any(c["component"] in ("Button", "Link") or "action" in c for c in components))

    def test_empty_period_has_no_fake_values_or_division_by_zero(self):
        data = {"summary": {"total_count": 0, "total_amount": Decimal("0")}, "by_recipient": []}
        model = build_payment_a2ui_messages(
            data, get_last_week_range(date(2026, 10, 27)), "测试公司"
        )[1]["updateDataModel"]["value"]
        self.assertEqual(model["summary"]["totalAmountText"], "¥0.00")
        self.assertEqual(model["summary"]["averageAmountText"], "—")
        self.assertEqual(model["summary"]["completionRateText"], "—")
        self.assertEqual(model["charts"]["dailyAmount"]["data"], [])
        self.assertEqual(model["charts"]["payeeAmount"]["data"], [])
        self.assertEqual(model["focusItems"], [])

    def test_top_five_and_other_payees_preserve_total(self):
        data = report_data()
        for i in range(4):
            data["by_recipient"].append({
                "recipient": f"其他收款人{i}", "count": 1, "amount": Decimal("10"),
                "details": [{"create_date": "2026-10-20", "amount": Decimal("10"), "status": "RUNNING"}],
            })
        data["summary"] = {"total_count": 8, "total_amount": Decimal("415")}
        model = build_payment_a2ui_messages(
            data, get_last_week_range(date(2026, 10, 27)), "测试公司", "month"
        )[1]["updateDataModel"]["value"]
        self.assertEqual(model["reportTitle"], "付款申请月报")
        self.assertEqual(model["summary"]["recipientCount"], 7)
        self.assertEqual(len(model["charts"]["payeeAmount"]["data"]), 6)
        self.assertEqual(model["payeeApplications"][-1]["count"], 2)
        self.assertAlmostEqual(sum(p["y"] for p in model["charts"]["payeeAmount"]["data"]), 0.0415)

    def test_calendar_month_includes_all_days_and_monthly_heading(self):
        frames = build_payment_a2ui_messages(
            report_data(), get_last_month_range(date(2026, 11, 1)), "测试公司", "month"
        )
        model = frames[1]["updateDataModel"]["value"]
        self.assertEqual(len(model["dailyApplications"]), 31)
        self.assertEqual(model["dailyApplications"][0]["date"], "2026-10-01")
        self.assertEqual(model["dailyApplications"][-1]["date"], "2026-10-31")
        self.assertEqual(sum(row["count"] for row in model["dailyApplications"]), 4)
        self.assertAlmostEqual(sum(row["y"] for row in model["charts"]["dailyAmount"]["data"]), 0.0375)
        heading = next(c for c in frames[2]["updateComponents"]["components"] if c["id"] == "focus-heading")
        self.assertEqual(heading["text"], "本月关注")

    def test_unknown_status_is_counted_and_labelled(self):
        data = report_data()
        data["by_recipient"][2]["details"][0]["status"] = "OTHER"
        model = build_payment_a2ui_messages(
            data, get_last_week_range(date(2026, 10, 27)), "测试公司"
        )[1]["updateDataModel"]["value"]
        other = next(row for row in model["statusBreakdown"] if row["status"] == "OTHER")
        self.assertEqual(other["amount"], 25)
        self.assertEqual(other["count"], 1)


class PaymentA2UIDeliveryTests(SimpleTestCase):
    def setUp(self):
        self.client = Mock()
        self.client.app.robot_code = "robot-code"
        self.a2ui = DingtalkA2UIClient(self.client)
        self.client.post.side_effect = self.success_response

    def success_response(self, endpoint, body):
        return {"success": True, "result": {
            "outTrackId": body["outTrackId"],
            "deliverResults": [{"spaceId": "cid-test", "spaceType": "IM_GROUP", "success": True}],
        }}

    def send(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            try:
                return self.a2ui.send_card("cid-test", messages(), path)
            finally:
                self.receipt = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def test_native_request_encodes_frames_and_finishes_in_one_call(self):
        frames = messages()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            receipt = self.a2ui.send_card("cid-test", frames, path)
            self.assertEqual(receipt, json.loads(path.read_text(encoding="utf-8")))
        self.client.post.assert_called_once()
        endpoint, body = self.client.post.call_args.args
        self.assertEqual(endpoint, "/v1.0/card/ai/instances/createAndDeliver")
        self.assertTrue(body["outTrackId"])
        self.assertEqual(body["openSpaceId"], "dtv1.card//IM_GROUP.cid-test")
        self.assertEqual(body["protocolVersion"], "1.0")
        self.assertEqual(body["flowStatus"], "FINISH")
        model = frames[1]["updateDataModel"]["value"]
        for value in (model["companyName"], model["reportTitle"], model["period"],
                      model["summary"]["totalCountText"], model["summary"]["totalAmountText"]):
            self.assertIn(value, body["summary"])
        self.assertEqual([json.loads(frame) for frame in body["a2uiMessages"]], frames)
        self.assertEqual(body["imGroupOpenDeliverModel"], {"robotCode": "robot-code"})
        self.assertEqual(body["imGroupOpenSpaceModel"], {"supportForward": False})
        self.assertEqual(receipt["outTrackId"], body["outTrackId"])
        self.assertEqual(receipt["flowStatus"], "FINISH")
        self.assertEqual(receipt["createResult"], self.success_response(endpoint, body)["result"])

    def test_each_send_uses_a_new_tracking_id(self):
        self.send()
        self.send()
        ids = [call.args[1]["outTrackId"] for call in self.client.post.call_args_list]
        self.assertEqual(len(set(ids)), 2)

    def test_missing_robot_code_refuses_before_network(self):
        for robot_code in ("", None):
            with self.subTest(robot_code=robot_code):
                self.client.app.robot_code = robot_code
                with self.assertRaises(DingtalkError):
                    self.a2ui.check_available()
                with self.assertRaises(DingtalkError):
                    self.send()
        self.client.post.assert_not_called()

    def test_rejected_or_unconfirmed_delivery_is_not_success(self):
        def rejected(kind):
            def response(endpoint, body):
                data = self.success_response(endpoint, body)
                result = data["result"]
                delivery = result["deliverResults"][0]
                if kind == "top_failure": data["success"] = False
                elif kind == "top_missing": data.pop("success")
                elif kind == "top_truthy": data["success"] = 1
                elif kind == "item_failure": delivery["success"] = False
                elif kind == "item_missing_success": delivery.pop("success")
                elif kind == "item_truthy": delivery["success"] = 1
                elif kind == "missing_items": result.pop("deliverResults")
                elif kind == "empty_items": result["deliverResults"] = []
                elif kind == "extra_items": result["deliverResults"].append(dict(delivery))
                elif kind == "wrong_group": delivery["spaceId"] = "dtv1.card//IM_GROUP.other"
                elif kind == "wrong_type": delivery["spaceType"] = "IM_ROBOT"
                elif kind == "wrong_track": result["outTrackId"] = "other-track"
                elif kind == "missing_track": result.pop("outTrackId")
                elif kind == "missing_result": data.pop("result")
                return data
            return response
        for kind in ("top_failure", "top_missing", "top_truthy", "item_failure",
                     "item_missing_success", "item_truthy", "missing_items", "empty_items",
                     "extra_items", "wrong_group", "wrong_type", "wrong_track", "missing_track", "missing_result"):
            with self.subTest(kind=kind):
                self.client.post.reset_mock()
                self.client.post.side_effect = rejected(kind)
                with self.assertRaises(DingtalkError):
                    self.send()
                self.client.post.assert_called_once()
                self.assertTrue(self.receipt["error"])

    def test_network_errors_keep_receipt_without_retry(self):
        for error in (TimeoutError("timeout: outcome unknown"), ConnectionError("connection lost"), DingtalkError("denied")):
            with self.subTest(error=error):
                self.client.post.reset_mock()
                self.client.post.side_effect = error
                with self.assertRaises(DingtalkError):
                    self.send()
                self.client.post.assert_called_once()
                self.assertTrue(self.receipt["error"])
                self.assertIn(str(error), str(self.receipt["error"]))
                self.assertEqual(self.receipt["outTrackId"], self.client.post.call_args.args[1]["outTrackId"])
