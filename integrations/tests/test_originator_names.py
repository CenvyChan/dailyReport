"""申请人姓名解析与历史回填。"""

import json
from io import StringIO
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from core.models import Company
from integrations.models import (
    DingtalkApp,
    DingtalkApprovalInstance,
    DingtalkProcessConfig,
    PaymentReportSnapshot,
)
from integrations.services.user_names import UserNameDirectory, name_from_title, resolve_originator_name


class OfflineClient:
    """回填命令测试不联网：通讯录不可用，只能走标题兜底。"""

    def __init__(self, app):
        self.app = app

    def get_user_name(self, userid):
        raise RuntimeError("offline")


class TitleNameTests(SimpleTestCase):
    def test_extracts_name_before_submit_phrase(self):
        self.assertEqual(name_from_title("赵雪姣提交的付款申请"), "赵雪姣")
        self.assertEqual(name_from_title("陆佳挺提交的日常报销单据"), "陆佳挺")

    def test_unrecognized_title_returns_blank(self):
        self.assertEqual(name_from_title("付款申请-补录"), "")
        self.assertEqual(name_from_title(None), "")
        self.assertEqual(name_from_title(""), "")


class UserNameDirectoryTests(SimpleTestCase):
    def fake_client(self, names):
        client = Mock()
        client.get_user_name.side_effect = lambda userid: names.get(userid, "")
        return client

    def test_directory_prefers_api_and_caches(self):
        client = self.fake_client({"u1": "陆佳挺"})
        directory = UserNameDirectory(client)
        raw = {"originator_userid": "u1", "title": "别人提交的付款申请"}
        self.assertEqual(directory.originator_name(raw), "陆佳挺")
        self.assertEqual(directory.originator_name(raw), "陆佳挺")
        self.assertEqual(client.get_user_name.call_count, 1)

    def test_api_failure_falls_back_to_title(self):
        client = Mock()
        client.get_user_name.side_effect = RuntimeError("no permission")
        directory = UserNameDirectory(client)
        raw = {"originator_userid": "u1", "title": "沈荧荧提交的付款申请"}
        self.assertEqual(directory.originator_name(raw), "沈荧荧")

    def test_stored_name_wins_over_api(self):
        client = self.fake_client({"u1": "接口名"})
        raw = {"originator_name": "已存名", "originator_userid": "u1", "title": "标题名提交的付款申请"}
        self.assertEqual(UserNameDirectory(client).originator_name(raw), "已存名")
        client.get_user_name.assert_not_called()

    def test_resolve_without_resolver_uses_stored_or_title(self):
        self.assertEqual(resolve_originator_name({"originator_name": "甲"}), "甲")
        self.assertEqual(resolve_originator_name({"title": "乙提交的付款申请"}), "乙")
        self.assertEqual(resolve_originator_name({}), "")


class SaveApprovalOriginatorTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(code="FNS", name="飞思")
        self.app = DingtalkApp.objects.create(
            company=self.company, name="app", app_key="k", app_secret="s"
        )
        self.process = DingtalkProcessConfig.objects.create(
            app=self.app, process_code="PROC", name="付款申请", amount_component="付款金额"
        )

    def raw(self, **extra):
        return {
            "title": extra.pop("title", "张三提交的付款申请"),
            "originator_userid": extra.pop("originator_userid", "u1"),
            "status": "COMPLETED",
            "form_component_values": [
                {"name": "付款金额", "value": "10"},
                {"name": "收款人", "value": "供应商甲"},
            ],
            **extra,
        }

    def test_sync_fills_name_from_title_when_directory_unavailable(self):
        from integrations.services.payment_organizations import save_approval

        client = Mock()
        client.get_user_name.side_effect = RuntimeError("no permission")
        resolver = UserNameDirectory(client).originator_name
        save_approval(self.app, self.process, self.raw(), "p1", name_resolver=resolver)
        row = DingtalkApprovalInstance.objects.get(process_instance_id="p1")
        self.assertEqual(row.originator_name, "张三")

    def test_resync_does_not_blank_an_existing_name(self):
        from integrations.services.payment_organizations import save_approval

        save_approval(self.app, self.process, self.raw(title="张三提交的付款申请"), "p1")
        # 后续同步拿不到姓名（标题也被改坏）时，不能把已回填的姓名清空。
        save_approval(self.app, self.process, self.raw(title="无前缀标题"), "p1")
        self.assertEqual(
            DingtalkApprovalInstance.objects.get(process_instance_id="p1").originator_name, "张三"
        )


class BackfillCommandTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(code="FNS", name="飞思")
        self.app = DingtalkApp.objects.create(
            company=self.company, name="app", app_key="k", app_secret="s"
        )
        self.process = DingtalkProcessConfig.objects.create(
            app=self.app, process_code="PROC", name="付款申请", amount_component="付款金额"
        )

    def approval(self, pid, title="张三提交的付款申请", userid="u1", name="", amount="10"):
        return DingtalkApprovalInstance.objects.create(
            company=self.company,
            process_code=self.process.process_code,
            process_name=self.process.name,
            process_instance_id=pid,
            title=title,
            originator_userid=userid,
            originator_name=name,
            status="COMPLETED",
            amount=amount,
            raw={"title": title, "originator_userid": userid},
        )

    def run_command(self, **options):
        output = StringIO()
        with patch(
            "integrations.management.commands.backfill_originator_names.DingtalkClient",
            OfflineClient,
        ):
            call_command("backfill_originator_names", stdout=output, **options)
        return output.getvalue()

    def test_dry_run_does_not_write(self):
        self.approval("p1")
        output = self.run_command()
        self.assertEqual(
            DingtalkApprovalInstance.objects.get(process_instance_id="p1").originator_name, ""
        )
        self.assertIn("DRY-RUN", output)

    def test_apply_writes_only_originator_name(self):
        self.approval("p1")
        row = DingtalkApprovalInstance.objects.get(process_instance_id="p1")
        before = (row.status, row.amount, row.updated_at)
        self.run_command(apply=True)
        row.refresh_from_db()
        self.assertEqual(row.originator_name, "张三")
        self.assertEqual((row.status, row.amount, row.updated_at), before)

    def test_already_filled_rows_are_untouched(self):
        self.approval("p1", name="原姓名", title="别人提交的付款申请")
        self.run_command(apply=True)
        self.assertEqual(
            DingtalkApprovalInstance.objects.get(process_instance_id="p1").originator_name,
            "原姓名",
        )

    def snapshot(self, originator=""):
        data = {
            "summary": {"total_count": 1, "total_amount": "10"},
            "by_recipient": [
                {
                    "recipient": "供应商甲",
                    "count": 1,
                    "amount": "10",
                    "details": [
                        {
                            "process_instance_id": "p1",
                            "amount": "10",
                            "status": "COMPLETED",
                            "create_date": "2026-11-03",
                            "reason": "货款",
                            "originator": originator,
                        }
                    ],
                }
            ],
        }
        return PaymentReportSnapshot.objects.create(
            company=self.company,
            report_type="week",
            period_start="2026-11-02",
            period_end="2026-11-08",
            process_code="PROC",
            period_label="2026年第45周",
            data=data,
        )

    def test_snapshot_originator_is_backfilled_keeping_other_fields(self):
        self.approval("p1")
        snapshot = self.snapshot()
        frozen = json.loads(json.dumps(snapshot.data, ensure_ascii=False))
        self.run_command(apply=True)
        snapshot.refresh_from_db()
        detail = snapshot.data["by_recipient"][0]["details"][0]
        self.assertEqual(detail["originator"], "张三")
        frozen["by_recipient"][0]["details"][0]["originator"] = "张三"
        self.assertEqual(snapshot.data, frozen)

    def test_snapshot_dry_run_keeps_frozen_data(self):
        self.approval("p1")
        snapshot = self.snapshot()
        before = json.loads(json.dumps(snapshot.data, ensure_ascii=False))
        output = self.run_command()
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.data, before)
        self.assertIn("将写入 1 条明细", output)
