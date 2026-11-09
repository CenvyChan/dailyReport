"""已探查薪资与报销流程的月度收集；预检完整集合后按申请公司幂等落库。"""

import hashlib
from collections import Counter
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import Company
from integrations.models import DingtalkApp, DingtalkCompanyMapping, SyncRun
from integrations.services.dingtalk_client import DingtalkClient
from integrations.services.expense_fields import normalize_expense_form, source_kind
from integrations.services.payment_organizations import application_company_name, resolve_company, save_approval
from integrations.services.user_names import UserNameDirectory
from integrations.services.erp_analysis.common import period_window


class Command(BaseCommand):
    help = "收集员工薪资发放与日常报销：按申请公司记录，不发送报表；默认遇到未映射公司时拒绝写入"

    def add_arguments(self, parser):
        parser.add_argument("--app-id", type=int, required=True)
        parser.add_argument("--period", required=True, help="申请发起月份 YYYY-MM")
        parser.add_argument("--dry-run", action="store_true", help="验证字段/金额/组织，不落库")
        parser.add_argument("--create-missing", action="store_true", help="将未映射的申请公司建立独立组织，不归入FNS")

    def handle(self, **options):
        try:
            first = datetime.strptime(options["period"], "%Y-%m").date().replace(day=1)
            last = period_window(first, 1)[0][1]
            app = DingtalkApp.objects.get(pk=options["app_id"], is_active=True)
        except (ValueError, DingtalkApp.DoesNotExist) as exc:
            raise CommandError("请指定启用的钉钉应用和有效 YYYY-MM 月份") from exc
        configs = [
            config
            for config in app.process_configs.filter(is_active=True).order_by("pk")
            if source_kind(config.name) in ("salary", "reimbursement")
        ]
        if not configs:
            raise CommandError("请先在审批模板配置中启用已探查的两个流程")
        client = DingtalkClient(app)
        start = timezone.make_aware(datetime.combine(first, datetime.min.time()))
        end = timezone.make_aware(datetime.combine(last + timedelta(days=1), datetime.min.time()))
        jobs, unknown, source_counts, company_counts = [], set(), Counter(), Counter()
        for config in configs:
            ids = client.list_instance_ids(
                config.process_code, int(start.timestamp() * 1000), int(end.timestamp() * 1000) - 1
            )
            for pid in dict.fromkeys(ids):
                raw = client.get_instance(pid)
                form = normalize_expense_form(config, raw.get("form_component_values", []))
                name = application_company_name(form)
                source_counts[config.name] += 1
                company_counts[name] += 1
                try:
                    resolve_company(app, form)
                except ValueError:
                    unknown.add(name)
                jobs.append((config, pid, raw))
        if unknown and not options["create_missing"]:
            raise CommandError("申请公司尚未映射（尚未写入任何实例）：" + "、".join(sorted(unknown)))
        self.stdout.write(f"月份 {first:%Y-%m}；来源笔数 {dict(source_counts)}；申请公司笔数 {dict(company_counts)}")
        if options["dry_run"]:
            self.stdout.write("只读校验完成，未写入数据或配置")
            return
        with transaction.atomic():
            for name in sorted(unknown):
                company = Company.objects.filter(name=name).first()
                if not company:
                    company = Company.objects.create(
                        code="DT-" + hashlib.sha256(name.encode()).hexdigest()[:12], name=name, is_active=True
                    )
                if not company.is_active:
                    raise CommandError("申请公司对应的组织被停用，拒绝继续")
                DingtalkCompanyMapping.objects.get_or_create(
                    app=app, application_company=name, defaults={"company": company}
                )
            run = SyncRun.objects.create(
                integration=SyncRun.Integration.DINGTALK,
                company=app.company,
                window_start=first,
                window_end=last,
                status=SyncRun.Status.RUNNING,
            )
            names = UserNameDirectory(client)
            for config, pid, raw in jobs:
                save_approval(
                    app, config, raw, pid, run=run, name_resolver=names.originator_name
                )
            run.status = SyncRun.Status.SUCCESS
            run.rows_upserted = len(jobs)
            run.finished_at = timezone.now()
            run.message = "支出审批按申请公司收集；未发送任何消息"
            run.save(update_fields=["status", "rows_upserted", "finished_at", "message"])
        self.stdout.write(f"收集完成：{len(jobs)} 张审批，已按申请公司幂等存储；未发送消息")
