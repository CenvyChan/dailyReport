"""钉钉审批实例同步：按公司×审批模板窗口拉取，按 process_instance_id 幂等 upsert。

本轮聚焦『付款申请』：K3 之外的费用，用于应付/已付区分。amount 从表单组件按配置名提取。
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from integrations.models import DingtalkApp, DingtalkApprovalInstance, SyncRun
from integrations.services.dingtalk_client import DingtalkClient

logger = logging.getLogger("integrations")


def _parse_dt(value):
    if not value:
        return None
    text = str(value).replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            naive = datetime.strptime(text[:19], fmt)
            return timezone.make_aware(naive) if timezone.is_naive(naive) else naive
        except ValueError:
            continue
    return None


def _amount_from_form(form_values, component_name):
    if not component_name or component_name not in form_values:
        return None
    raw = form_values[component_name]
    try:
        return Decimal(str(raw).replace(",", "").strip())
    except (InvalidOperation, ValueError, TypeError):
        return None


def _flatten_form(instance):
    values = {}
    for item in instance.get("form_component_values", []) or []:
        name = item.get("name")
        if name is not None:
            values[name] = item.get("value")
    return values


def _upsert_instance(company, process, instance, run):
    pid = instance.get("business_id") or instance.get("process_instance_id") or instance.get("id")
    if not pid:
        return False
    form_values = _flatten_form(instance)
    DingtalkApprovalInstance.objects.update_or_create(
        company=company,
        process_instance_id=str(pid),
        defaults={
            "process_code": process.process_code,
            "process_name": process.name,
            "title": instance.get("title") or "",
            "originator_userid": instance.get("originator_userid") or "",
            "originator_name": instance.get("originator_name") or "",
            "dept_name": instance.get("originator_dept_name") or "",
            "status": instance.get("status") or "",
            "result": instance.get("result") or "",
            "amount": _amount_from_form(form_values, process.amount_component),
            "create_time": _parse_dt(instance.get("create_time")),
            "finish_time": _parse_dt(instance.get("finish_time")),
            "form_values": form_values,
            "raw": instance,
            "sync_run": run,
        },
    )
    return True


def sync_dingtalk(as_of=None, company=None, dry_run=False, client_factory=DingtalkClient):
    """对每个启用的钉钉应用×审批模板，拉取窗口内审批实例并落库。返回逐公司结果。"""
    now = timezone.now() if as_of is None else datetime.combine(as_of, datetime.min.time())
    if timezone.is_naive(now):
        now = timezone.make_aware(now)
    apps = DingtalkApp.objects.filter(is_active=True).select_related("company")
    if company is not None:
        apps = apps.filter(company=company)
    results = []

    for app in apps:
        processes = list(app.process_configs.filter(is_active=True))
        run = None
        if not dry_run:
            run = SyncRun.objects.create(
                integration=SyncRun.Integration.DINGTALK,
                company=app.company,
                window_end=now.date(),
                status=SyncRun.Status.RUNNING,
            )
        try:
            client = client_factory(app)
            upserted = 0
            earliest = now.date()
            for process in processes:
                start = now - timedelta(days=process.lookback_days or 30)
                earliest = min(earliest, start.date())
                start_ms = int(start.timestamp() * 1000)
                end_ms = int(now.timestamp() * 1000)
                ids = client.list_instance_ids(process.process_code, start_ms, end_ms)
                for pid in ids:
                    instance = client.get_instance(pid)
                    if not dry_run and _upsert_instance(app.company, process, instance, run):
                        upserted += 1
                if dry_run:
                    upserted += len(ids)
            if run is not None:
                run.status = SyncRun.Status.SUCCESS
                run.rows_upserted = upserted
                run.window_start = earliest
                run.finished_at = timezone.now()
                run.save(update_fields=["status", "rows_upserted", "window_start", "finished_at"])
            results.append({"company": app.company, "upserted": upserted, "error": None})
        except Exception as exc:  # noqa: BLE001
            logger.exception("钉钉同步失败 company=%s", app.company)
            if run is not None:
                run.status = SyncRun.Status.FAILED
                run.message = str(exc)
                run.finished_at = timezone.now()
                run.save(update_fields=["status", "message", "finished_at"])
            results.append({"company": app.company, "upserted": 0, "error": str(exc)})
    return results
