"""审计、备份并重建付款审批的组织归属；默认只读。"""
import hashlib
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core import serializers
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import Company
from integrations.models import DingtalkApp, DingtalkCompanyMapping
from integrations.services.dingtalk_client import DingtalkClient
from integrations.services.payment_organizations import (
    PAYMENT_REPORT_COMPANY_APPLICATION_NAMES, application_company_name, approval_scope, flatten_form, resolve_company, save_approval,
)


class Command(BaseCommand):
    help = "按申请公司审计付款审批；--apply 备份后重分类；--refresh 从钉钉重新同步指定期间"

    def add_arguments(self, parser):
        parser.add_argument("--app-id", type=int, required=True)
        parser.add_argument("--apply", action="store_true", help="备份后实际创建映射、重分类并合并已证实的重复审批")
        parser.add_argument("--create-missing", action="store_true", help="为申请公司原值创建缺少的项目组织，不自动创建推送群")
        parser.add_argument("--refresh", action="store_true", help="从钉钉列表接口重新获取审批详情及规范实例ID")
        parser.add_argument("--start", help="重新同步起日 YYYY-MM-DD（含）")
        parser.add_argument("--end", help="重新同步止日 YYYY-MM-DD（含），默认今天")
        parser.add_argument("--backup-dir", default=str(Path(settings.BASE_DIR) / "backups"))

    def handle(self, **options):
        try:
            app = DingtalkApp.objects.select_related("company").get(pk=options["app_id"], is_active=True)
        except DingtalkApp.DoesNotExist as exc:
            raise CommandError("找不到启用的来源钉钉应用") from exc
        configs = list(app.process_configs.filter(is_active=True, name__icontains="付款申请"))
        if not configs:
            raise CommandError("该应用没有启用的付款申请模板")
        jobs = []
        source_rows = []
        for config in configs:
            # 同一流程可能残留两种 ID；优先使用最近同步的源端详情，避免审批状态倒退。
            rows = list(approval_scope(app, config.process_code).order_by("-updated_at", "-pk"))
            source_rows.extend(rows)
            if options["refresh"]:
                if not options.get("start"):
                    raise CommandError("--refresh 必须指定 --start，避免猜测清理和同步的历史范围")
                try:
                    start = date.fromisoformat(options["start"])
                    end = date.fromisoformat(options.get("end") or timezone.localdate().isoformat())
                except ValueError as exc:
                    raise CommandError("日期格式必须是 YYYY-MM-DD") from exc
                if end < start:
                    raise CommandError("--end 不能早于 --start")
                client = DingtalkClient(app)
                cursor = start
                seen = set()
                while cursor <= end:
                    stop = min(cursor + timedelta(days=120), end + timedelta(days=1))
                    begin_dt = timezone.make_aware(datetime.combine(cursor, datetime.min.time()))
                    stop_dt = timezone.make_aware(datetime.combine(stop, datetime.min.time()))
                    for pid in client.list_instance_ids(config.process_code, int(begin_dt.timestamp() * 1000), int(stop_dt.timestamp() * 1000) - 1):
                        if pid not in seen:
                            jobs.append((config, str(pid), client.get_instance(pid)))
                            seen.add(pid)
                    cursor = stop
            else:
                for row in rows:
                    raw = dict(row.raw or {})
                    raw.setdefault("form_component_values", row.form_values)
                    for key in ("status", "result", "title", "originator_userid", "originator_name", "create_time", "finish_time"):
                        value = getattr(row, key)
                        raw.setdefault(key, value.isoformat() if isinstance(value, datetime) else value)
                    raw.setdefault("originator_dept_name", row.dept_name)
                    pid = raw.get("process_instance_id") or raw.get("id") or row.process_instance_id
                    jobs.append((config, str(pid), raw))
        # 旧同步曾把业务编号存作实例ID；只有原始数据明确给出对应关系才归并。
        canonical_ids = {}
        for config, pid, raw in jobs:
            business_id = raw.get("business_id")
            if business_id and str(business_id) != pid:
                key = (config.process_code, str(business_id))
                if key in canonical_ids and canonical_ids[key] != pid:
                    raise CommandError("同一业务编号对应多个实例ID，停止自动合并")
                canonical_ids[key] = pid
        jobs = [(config, canonical_ids.get((config.process_code, pid), pid), raw) for config, pid, raw in jobs]
        summary = defaultdict(lambda: {"count": 0, "amount": Decimal("0")})
        unknown = 0
        unique_jobs = {}
        for config, pid, raw in jobs:
            key = (config.process_code, pid)
            # 同一业务编号绝不作为去重依据；只使用规范实例ID。
            if key not in unique_jobs:
                unique_jobs[key] = (config, pid, raw)
        names = set()
        for config, pid, raw in unique_jobs.values():
            form = flatten_form(raw.get("form_component_values"))
            name = application_company_name(form)
            if not name:
                unknown += 1
            else:
                names.add(name)
            bucket = summary[name or "[缺少申请公司]"]
            bucket["count"] += 1
            try:
                bucket["amount"] += Decimal(str(form.get(config.amount_component) or 0).replace(",", ""))
            except Exception as exc:
                raise CommandError(f"审批 {pid} 金额无法解析，未执行清理") from exc
        self.stdout.write(f"来源应用 #{app.pk}；本地 {len(source_rows)} 条；本次唯一审批 {len(unique_jobs)} 条；申请公司 {len(names)} 家")
        for name, bucket in sorted(summary.items()):
            self.stdout.write(f"{name}: {bucket['count']} 笔 / {bucket['amount']:,.2f}")
        if not options["apply"]:
            self.stdout.write("[只读预览] 未修改数据；检查申请公司后使用 --apply，缺少的组织可使用 --create-missing")
            return
        if unknown:
            raise CommandError(f"{unknown} 条审批缺少申请公司，未修改任何数据；请先核对源表单")
        mappings = {m.application_company: m.company for m in app.company_mappings.select_related("company")}
        target_codes = {name: code for code, name in PAYMENT_REPORT_COMPANY_APPLICATION_NAMES.items()}
        target_companies = {}
        for name in names:
            code = target_codes.get(name)
            if code:
                company = Company.objects.filter(code=code, is_active=True).first()
                if company is None:
                    raise CommandError(
                        f"目标申请公司「{name}」对应的项目组织代码 {code} 不存在或未启用；拒绝自动创建重复公司"
                    )
                target_companies[name] = company
        missing = [
            name for name in names
            if name not in mappings
            and name not in target_companies
            and not Company.objects.filter(name=name).exists()
        ]
        if missing and not options["create_missing"]:
            raise CommandError("以下申请公司尚无项目组织，请先配置映射或使用 --create-missing：" + "、".join(sorted(missing)))
        backup_dir = Path(options["backup_dir"])
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f"payment-organizations-{app.pk}-{timezone.now():%Y%m%d-%H%M%S-%f}.json"
        database = settings.DATABASES["default"]
        if database["ENGINE"] == "django.db.backends.sqlite3" and Path(database["NAME"]).is_file():
            sqlite_backup = backup.with_suffix(".sqlite3")
            source = sqlite3.connect(str(database["NAME"]))
            target = sqlite3.connect(str(sqlite_backup))
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
            self.stdout.write(f"完整数据库备份: {sqlite_backup}")
        objects = list(Company.objects.all()) + list(app.company_mappings.all()) + source_rows
        with backup.open("x", encoding="utf-8") as handle:
            handle.write(serializers.serialize("json", objects, ensure_ascii=False, indent=2))
        self.stdout.write(f"修复前备份: {backup}")
        try:
            with transaction.atomic():
                for name in sorted(names):
                    if name in target_companies:
                        company = target_companies[name]
                        DingtalkCompanyMapping.objects.update_or_create(
                            app=app, application_company=name, defaults={"company": company}
                        )
                        mappings[name] = company
                        continue
                    if name in mappings:
                        continue
                    company = Company.objects.filter(name=name).first()
                    if company is None:
                        code = "DT-" + hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
                        company = Company.objects.create(code=code, name=name, is_active=True)
                    DingtalkCompanyMapping.objects.create(app=app, application_company=name, company=company)
                for config, pid, raw in unique_jobs.values():
                    resolve_company(app, raw.get("form_component_values"))
                for config, pid, raw in unique_jobs.values():
                    save_approval(app, config, raw, pid, repair=True)
        except Exception as exc:
            raise CommandError(f"修复已回滚：{exc}；备份保留在 {backup}") from exc
        self.stdout.write(self.style.SUCCESS("申请公司重分类及本次同步完成；仅合并实例ID/业务编号有明确对应关系的重复记录。"))
        self.stdout.write("未配置的组织推送群不会自动创建；请在后台分别配置各组织的群与付款日报/周报周期。")
