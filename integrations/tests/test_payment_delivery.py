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
from integrations.models import DingtalkApp, DingtalkApprovalInstance, DingtalkCompanyMapping
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

    def test_new_api_error_preserves_template_error_code(self):
        body = {"code": "param.templateUnpublished", "message": "param.templateUnpublished"}
        for method in ("post", "get"):
            with self.subTest(method=method):
                with self.assertRaises(DingtalkError) as raised:
                    self.request(method, body, status=400)
                self.assertEqual(raised.exception.code, "param.templateUnpublished")

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

    def test_unpublished_template_explains_how_to_publish(self):
        self.client = DingtalkClient(SimpleNamespace())
        body = {"code": "param.templateUnpublished", "message": "param.templateUnpublished"}
        response = Mock(status_code=400, text=json.dumps(body))
        response.json.return_value = body
        with patch.object(self.client, "token", return_value="test-token"), patch(
            "integrations.services.dingtalk_client._requests"
        ) as requests:
            requests.return_value.post.return_value = response
            with self.assertRaises(DingtalkError) as raised:
                self.send()
        self.assertIn("template.schema", str(raised.exception))
        self.assertIn("未发布", str(raised.exception))
        self.assertIn("https://open-dev.dingtalk.com/fe/card", str(raised.exception))
        self.assertIn("param.templateUnpublished", str(raised.exception))

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
        self.assertEqual(
            sorted(detail["create_date"] for row in data["by_recipient"] for detail in row["details"]),
            ["2026-10-19", "2026-10-25"],
        )

    @override_settings(USE_TZ=False)
    def test_timezone_disabled_keeps_naive_boundaries(self):
        for getter in (get_last_week_range, get_last_month_range):
            period = getter(date(2026, 10, 26))
            self.assertTrue(timezone.is_naive(period["start"]))
            self.assertTrue(timezone.is_naive(period["end"]))


class PaymentCommandDeliveryTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(code="FNS", name="飞诺斯电子科技有限公司")
        self.app = DingtalkApp.objects.create(
            company=self.company, app_key="key", app_secret="secret",
            robot_code="robot-code", card_template_id="unpublished.schema",
        )
        DingtalkCompanyMapping.objects.create(
            app=self.app,
            application_company="慈溪飞诺斯电子科技有限公司",
            company=self.company,
        )
        DingtalkApprovalInstance.objects.create(
            company=self.company, process_instance_id="SEND-A2UI", process_code="PAYMENT",
            status="RUNNING", amount=Decimal("123.45"),
            create_time=timezone.make_aware(datetime(2026, 10, 19)),
            form_values=[
                {"name": "申请公司", "value": "慈溪飞诺斯电子科技有限公司"},
                {"name": "收款人", "value": "测试供应商"},
            ],
        )

    def run_report(self, client, a2ui=None, **options):
        output = StringIO()
        client.upload_media.return_value = "test-media-id"
        a2ui = a2ui or Mock()
        a2ui.send_card.return_value = {"outTrackId": "native-card-test", "flowStatus": "FINISH", "createResult": {"outTrackId": "native-card-test"}}
        self.a2ui = a2ui
        module = "integrations.management.commands.send_payment_report"
        with TemporaryDirectory() as directory, ExitStack() as stack:
            self.client_factory = stack.enter_context(patch(f"{module}.DingtalkClient", return_value=client))
            self.a2ui_factory = stack.enter_context(patch(f"{module}.DingtalkA2UIClient", return_value=a2ui))
            stack.enter_context(patch(
                f"{module}.generate_payment_excel",
                side_effect=lambda data, period, path: Path(path).write_bytes(b"test-excel"),
            ))
            stack.enter_context(patch(f"{module}.build_payment_report_message", return_value="付款周报文本"))
            try:
                call_command(
                    "send_payment_report", "week", company=self.company.code,
                    group_id="cid-test", process_code="PAYMENT", base_date="2026-10-26",
                    output_dir=directory, stdout=output, **options,
                )
                paths = list(Path(directory).glob("*.a2ui.json"))
                self.exported = json.loads(paths[0].read_text(encoding="utf-8")) if paths else None
            except CommandError as exc:
                exc.command_output = output.getvalue()
                exc.args = (f"{exc}\n{output.getvalue()}",)
                raise
        return output.getvalue()

    def test_card_error_fails_without_falling_back_to_text(self):
        client = Mock()
        a2ui = Mock()
        a2ui.send_card.side_effect = DingtalkError("A2UI authentication failed")
        with self.assertRaises(CommandError) as raised:
            self.run_report(client, a2ui)
        output = raised.exception.command_output
        self.assertIn("A2UI 卡片发送失败", output)
        self.assertIn("0 成功, 1 失败", output)
        self.assertNotIn("文本消息已发送", output)
        self.assertNotIn("文件消息已发送", output)
        self.assertNotIn("✓ 发送成功", output)
        a2ui.send_card.assert_called_once()
        client.post.assert_not_called()

    def test_card_success_sends_file_and_counts_as_success(self):
        client = Mock()
        client.post.return_value = {"processQueryKey": "file-key"}
        output = self.run_report(client)
        self.client_factory.assert_called_once_with(self.app)
        self.a2ui_factory.assert_called_once_with(client)
        self.assertIn("A2UI 卡片已发送并完结", output)
        self.assertIn("文件消息已发送", output)
        self.assertIn("1 成功, 0 失败", output)
        client.post.assert_called_once()
        self.assertEqual(client.post.call_args.args[1]["msgKey"], "sampleFile")
        frames = self.a2ui.send_card.call_args.args[1]
        self.assertEqual(frames, self.exported)
        self.assertEqual(frames[1]["updateDataModel"]["value"]["summary"]["totalAmountText"], "¥123.45")

    def test_no_template_still_uses_a2ui(self):
        self.app.card_template_id = ""
        self.app.save(update_fields=["card_template_id"])
        client = Mock()
        client.post.return_value = {"processQueryKey": "file-key"}
        self.run_report(client)
        self.a2ui.send_card.assert_called_once()
        self.assertEqual(client.post.call_args.args[1]["msgKey"], "sampleFile")

    def test_no_card_explicitly_sends_text_and_file(self):
        client = Mock()
        client.post.side_effect = [{"processQueryKey": "text-key"}, {"processQueryKey": "file-key"}]
        output = self.run_report(client, no_card=True)
        self.assertIn("文本消息已发送", output)
        self.assertIn("文件消息已发送", output)
        self.assertIn("1 成功, 0 失败", output)
        self.a2ui.send_card.assert_not_called()
        self.a2ui.check_available.assert_not_called()
        self.assertEqual(
            [call.args[1].get("msgKey") for call in client.post.call_args_list],
            ["sampleText", "sampleFile"],
        )

    def test_file_failure_is_counted_as_failure(self):
        client = Mock()
        client.post.side_effect = DingtalkError("file upload failed")
        with self.assertRaises(CommandError) as raised:
            self.run_report(client)
        self.assertIn("0 成功, 1 失败", raised.exception.command_output)
        self.assertNotIn("✓ 发送成功", raised.exception.command_output)

    def test_dry_run_exports_live_json_without_any_network_client(self):
        client = Mock()
        output = self.run_report(client, dry_run=True)
        self.assertIn("生成A2UI:", output)
        self.assertEqual(self.exported[1]["updateDataModel"]["value"]["summary"]["totalCount"], 1)
        self.assertEqual(self.exported[1]["updateDataModel"]["value"]["reportMeta"]["dataMode"], "live")
        client.upload_media.assert_not_called()
        client.post.assert_not_called()
        self.a2ui.check_available.assert_not_called()
        self.a2ui.send_card.assert_not_called()

    def test_missing_robot_code_stops_before_upload(self):
        client = Mock()
        a2ui = Mock()
        a2ui.check_available.side_effect = DingtalkError("未配置 robot_code")
        with self.assertRaisesMessage(CommandError, "未配置 robot_code"):
            self.run_report(client, a2ui)
        client.upload_media.assert_not_called()
        a2ui.send_card.assert_not_called()
