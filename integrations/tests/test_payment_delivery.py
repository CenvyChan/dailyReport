"""付款卡片接口协议、失败判定和报表命令回归测试。"""

import json
from contextlib import ExitStack
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch
import warnings

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from core.models import Company
from integrations.models import DingtalkApp, DingtalkApprovalInstance
from integrations.services.dingtalk_client import DingtalkClient, DingtalkError
from integrations.services.payment_card import send_interactive_card
from integrations.services.payment_report import (
    analyze_payment_applications,
    get_last_month_range,
    get_last_week_range,
)


class DingtalkResponseTests(SimpleTestCase):
    def request(self, method, body, status=200):
        client = DingtalkClient(SimpleNamespace())
        response = Mock(status_code=status, text=json.dumps(body))
        response.json.return_value = body
        with patch.object(client, "token", return_value="test-token"), patch(
            "integrations.services.dingtalk_client._requests"
        ) as requests:
            getattr(requests.return_value, method).return_value = response
            return getattr(client, method)("/v1.0/test", {})

    def test_new_api_errors_are_not_treated_as_success(self):
        cases = [
            (200, {"code": "MissingStringValue", "message": "StringValue is mandatory for this action."}),
            (400, {"message": "Bad Request"}),
            (200, {"success": False, "message": "delivery failed"}),
            (200, {"errcode": 40035, "errmsg": "invalid parameter"}),
        ]
        for method in ("post", "get"):
            for status, body in cases:
                with self.subTest(method=method, status=status, body=body):
                    with self.assertRaises(DingtalkError):
                        self.request(method, body, status)

    def test_success_responses_remain_compatible(self):
        for method in ("post", "get"):
            for body in ({"processQueryKey": "message-key"}, {"errcode": 0, "result": {}}, {"success": True}):
                with self.subTest(method=method, body=body):
                    self.assertEqual(self.request(method, body), body)


class PaymentCardDeliveryTests(SimpleTestCase):
    def setUp(self):
        self.client = Mock()
        self.client.post.return_value = {
            "success": True,
            "result": {"deliverResults": [{"spaceId": "cid-test", "success": True}]},
        }

    def send(self, data=None):
        return send_interactive_card(
            self.client, "cid-test", data or {"title": "付款周报"}, "template.schema", "robot-code"
        )

    def test_uses_card_creation_and_delivery_api(self):
        result = self.send()
        path, payload = self.client.post.call_args.args
        self.assertEqual(path, "/v1.0/card/instances/createAndDeliver")
        self.assertEqual(payload["cardTemplateId"], "template.schema")
        self.assertEqual(payload["openSpaceId"], "dtv1.card//IM_GROUP.cid-test")
        self.assertEqual(payload["imGroupOpenDeliverModel"], {"robotCode": "robot-code"})
        self.assertEqual(payload["userIdType"], 1)
        self.assertTrue(payload["outTrackId"])
        self.assertNotIn("msgKey", payload)
        self.assertNotIn("msgParam", payload)
        self.assertEqual(result, self.client.post.return_value)

    def test_card_parameters_are_strings_without_mutating_input(self):
        data = {"title": "付款周报", "total": 0, "enabled": True, "items": [{"name": "供应商甲"}], "config": {"a": 1}}
        self.send(data)
        params = self.client.post.call_args.args[1]["cardData"]["cardParamMap"]
        self.assertTrue(all(isinstance(value, str) for value in params.values()))
        self.assertEqual(params["title"], data["title"])
        self.assertEqual(params["total"], "0")
        self.assertEqual(params["enabled"], "true")
        self.assertEqual(json.loads(params["items"]), data["items"])
        self.assertEqual(json.loads(params["config"]), data["config"])
        self.assertIsInstance(data["items"], list)
        self.assertEqual(data["total"], 0)

    def test_rejected_or_unconfirmed_delivery_raises(self):
        for response in (
            {"success": False},
            {"success": True, "result": {"deliverResults": [{"success": False, "errorCode": "Forbidden"}]}},
            {"success": True, "result": {"deliverResults": []}},
            {"success": True},
        ):
            with self.subTest(response=response):
                self.client.post.return_value = response
                with self.assertRaises(DingtalkError):
                    self.send()


@override_settings(USE_TZ=True, TIME_ZONE="Asia/Shanghai")
class PaymentPeriodTimezoneTests(TestCase):
    def test_week_and_month_boundaries_are_aware_local_times(self):
        with timezone.override("Asia/Shanghai"):
            for period, start, end in (
                (get_last_week_range(date(2026, 10, 26)), date(2026, 10, 19), date(2026, 10, 25)),
                (get_last_month_range(date(2026, 10, 26)), date(2026, 9, 1), date(2026, 9, 30)),
            ):
                with self.subTest(label=period["label"]):
                    self.assertTrue(timezone.is_aware(period["start"]))
                    self.assertTrue(timezone.is_aware(period["end"]))
                    self.assertEqual(period["start"].utcoffset(), timedelta(hours=8))
                    self.assertEqual(period["start_date"], start)
                    self.assertEqual(period["end_date"], end)
                    self.assertEqual(period["start"].time(), datetime.min.time())
                    self.assertEqual(period["end"].time(), datetime.max.time())

    def test_week_query_includes_only_local_period_without_warnings(self):
        company = Company.objects.create(code="TZ-TEST", name="时区测试公司")
        period = get_last_week_range(date(2026, 10, 26))
        for index, timestamp in enumerate((
            datetime(2026, 10, 18, 23, 59, 59, 999999),
            datetime(2026, 10, 19),
            datetime(2026, 10, 25, 23, 59, 59, 999999),
            datetime(2026, 10, 26),
        )):
            DingtalkApprovalInstance.objects.create(
                company=company, process_instance_id=f"TZ-{index}", process_code="PAYMENT",
                status="COMPLETED", amount=Decimal("10"),
                create_time=timezone.make_aware(timestamp, timezone.get_default_timezone()),
            )
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            data = analyze_payment_applications(company, period["start"], period["end"], "PAYMENT")
        self.assertEqual(data["summary"]["total_count"], 2)
        self.assertEqual(data["summary"]["total_amount"], Decimal("20"))

    @override_settings(USE_TZ=False)
    def test_timezone_disabled_keeps_naive_boundaries(self):
        for getter in (get_last_week_range, get_last_month_range):
            period = getter(date(2026, 10, 26))
            self.assertTrue(timezone.is_naive(period["start"]))
            self.assertTrue(timezone.is_naive(period["end"]))


class PaymentCommandDeliveryTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(code="SEND-TEST", name="发送测试公司")
        DingtalkApp.objects.create(
            company=self.company, app_key="key", app_secret="secret",
            robot_code="robot-code", card_template_id="template.schema",
        )

    def run_report(self, client):
        output = StringIO()
        client.upload_media.return_value = "test-media-id"
        module = "integrations.management.commands.send_payment_report"
        with TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(patch(f"{module}.DingtalkClient", return_value=client))
            stack.enter_context(patch(
                f"{module}.generate_payment_excel",
                side_effect=lambda data, period, path: Path(path).write_bytes(b"test-excel"),
            ))
            stack.enter_context(patch(f"{module}.build_payment_report_message", return_value="付款周报文本"))
            stack.enter_context(patch(
                "integrations.services.payment_card.build_payment_card_data", return_value={"title": "付款周报"}
            ))
            try:
                call_command(
                    "send_payment_report", "week", company=self.company.code, group_id="cid-test",
                    process_code="PAYMENT", base_date="2026-10-26", output_dir=directory, stdout=output,
                )
            except CommandError as exc:
                exc.command_output = output.getvalue()
                exc.args = (f"{exc}\n{output.getvalue()}",)
                raise
        return output.getvalue()

    def test_card_error_falls_back_to_text_without_false_card_success(self):
        client = Mock()
        client.post.side_effect = [
            DingtalkError("MissingStringValue: StringValue is mandatory for this action."),
            {"processQueryKey": "text-key"}, {"processQueryKey": "file-key"},
        ]
        output = self.run_report(client)
        self.assertNotIn("互动卡片已发送", output)
        self.assertIn("卡片发送失败", output)
        self.assertIn("降级为文本消息", output)
        self.assertIn("文本消息已发送", output)
        self.assertIn("1 成功, 0 失败", output)
        self.assertEqual([call.args[1].get("msgKey") for call in client.post.call_args_list], [None, "sampleText", "sampleFile"])

    def test_file_failure_is_counted_as_failure(self):
        client = Mock()
        client.post.side_effect = [
            {"success": True, "result": {"deliverResults": [{"success": True}]}},
            DingtalkError("file upload failed"),
        ]
        with self.assertRaises(CommandError) as raised:
            self.run_report(client)
        self.assertIn("0 成功, 1 失败", raised.exception.command_output)
        self.assertNotIn("✓ 发送成功", raised.exception.command_output)
