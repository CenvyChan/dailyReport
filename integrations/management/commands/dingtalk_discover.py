"""钉钉审批模板字段探查：拉几条真实审批实例，打印表单控件名与样例值。

用于在不清楚表单字段映射时，先看清「付款金额」等控件在钉钉里的**确切名称**，
再据此回填 DingtalkProcessConfig.amount_component。只读，不写库。
"""

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import Company
from integrations.models import DingtalkApp
from integrations.services.dingtalk_client import DingtalkClient
from integrations.services.dingtalk_sync import _flatten_form


class Command(BaseCommand):
    help = "探查钉钉审批模板的表单控件名（确定 amount_component 等字段映射）。只读。"

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True, help="公司代码，如 FNS。")
        parser.add_argument("--process-code", help="审批模板 process_code；缺省用该公司已配置的模板。")
        parser.add_argument("--days", type=int, default=30, help="回看天数，默认 30。")
        parser.add_argument("--limit", type=int, default=3, help="每模板最多打印几条实例，默认 3。")

    def handle(self, *args, **options):
        try:
            company = Company.objects.get(code=options["company"])
        except Company.DoesNotExist as exc:
            raise CommandError(f"找不到公司代码：{options['company']}") from exc
        try:
            app = DingtalkApp.objects.get(company=company, is_active=True)
        except DingtalkApp.DoesNotExist as exc:
            raise CommandError(f"公司 {company.code} 未配置启用的钉钉应用，请先在后台建 DingtalkApp。") from exc

        if options["process_code"]:
            codes = [(options["process_code"], options["process_code"])]
        else:
            codes = [(p.process_code, p.name) for p in app.process_configs.filter(is_active=True)]
            if not codes:
                raise CommandError("未配置审批模板，也未传 --process-code。先建 DingtalkProcessConfig 或用 --process-code 指定。")

        client = DingtalkClient(app)
        now = timezone.now()
        start_ms = int((now - timedelta(days=options["days"])).timestamp() * 1000)
        end_ms = int(now.timestamp() * 1000)

        for code, name in codes:
            self.stdout.write(self.style.MIGRATE_HEADING(f"== 模板 {name} ({code}) =="))
            try:
                ids = client.list_instance_ids(code, start_ms, end_ms)
            except Exception as exc:  # noqa: BLE001 - 探查工具，逐模板容错
                self.stdout.write(self.style.ERROR(f"  拉取实例列表失败：{exc}"))
                continue
            self.stdout.write(f"  近 {options['days']} 天实例数：{len(ids)}")
            seen = set()
            for pid in ids[: options["limit"]]:
                inst = client.get_instance(pid)
                form = _flatten_form(inst)
                seen.update(form.keys())
                self.stdout.write(
                    f"  ── {pid} | 标题:{inst.get('title','')} | 状态:{inst.get('status','')}/{inst.get('result','')}"
                )
                for k, v in form.items():
                    sval = str(v)
                    self.stdout.write(f"       控件「{k}」= {sval[:50] + '…' if len(sval) > 50 else sval}")
            if seen:
                self.stdout.write(self.style.SUCCESS(f"  控件名汇总（可选作 amount_component）：{sorted(seen)}"))
