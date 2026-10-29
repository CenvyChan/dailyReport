"""付款审批按申请公司归属，所有同步入口共用同一实例ID与表单格式。"""
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from integrations.models import DingtalkApprovalInstance, DingtalkApp, DingtalkCompanyMapping

PAYMENT_REPORT_COMPANY_APPLICATION_NAMES = {
    "FNS": "慈溪飞诺斯电子科技有限公司",
    "NBHH": "宁波汇慧电子有限公司",
}
PAYMENT_REPORT_COMPANY_CODES = tuple(PAYMENT_REPORT_COMPANY_APPLICATION_NAMES)


def flatten_form(values):
    if isinstance(values, dict):
        return dict(values)
    return {item["name"]: item.get("value") for item in (values or []) if isinstance(item, dict) and item.get("name")}


def application_company_name(values):
    value = flatten_form(values).get("申请公司")
    if value in (None, ""):
        return ""
    if not isinstance(value, str):
        raise ValueError("申请公司不是单一文本值，请先核对审批表单")
    return value.strip()


def resolve_company(app, values):
    form = flatten_form(values)
    name = application_company_name(form)
    if name:
        mapping = app.company_mappings.select_related("company").filter(application_company=name).first()
        if mapping:
            company = mapping.company
        elif name == app.company.name:
            company = app.company
        else:
            raise ValueError(f"申请公司「{name}」尚未映射到项目组织，请先运行 reconcile_payment_organizations")
        if not company.is_active:
            raise ValueError(f"申请公司「{name}」对应的组织未启用")
        return company
    if "申请公司" in form or app.company_mappings.exists():
        raise ValueError("审批缺少申请公司，拒绝混入应用所属公司")
    # 兼容未采用申请公司字段的既有模板。
    return app.company


def approval_scope(app, process_code=None):
    company_ids = app.company_mappings.values_list("company_id", flat=True)
    query = DingtalkApprovalInstance.objects.filter(Q(company_id=app.company_id) | Q(company_id__in=company_ids))
    if process_code:
        query = query.filter(process_code=process_code)
    return query


def payment_app_for_company(company, app_id=None):
    apps = DingtalkApp.objects.filter(is_active=True).filter(Q(company=company) | Q(company_mappings__company=company)).distinct()
    if app_id:
        apps = apps.filter(pk=app_id)
    matches = list(apps)
    if len(matches) != 1:
        raise ValueError(f"组织 {company.code} 需明确关联一个启用的钉钉应用（当前 {len(matches)} 个），可用 --app-id 指定")
    return matches[0]


def parse_datetime(value):
    if not value:
        return None
    if isinstance(value, (int, float)) or str(value).isdigit():
        result = datetime.fromtimestamp(float(value) / 1000, tz=timezone.get_current_timezone())
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return timezone.make_aware(result) if timezone.is_naive(result) else result


def instance_defaults(app, process, raw, instance_id):
    form = flatten_form(raw.get("form_component_values", []))
    try:
        amount = Decimal(str(form.get(process.amount_component, "")).replace(",", "").strip())
    except (InvalidOperation, ValueError, TypeError):
        amount = None
    return {
        "company": resolve_company(app, form) if "付款申请" in process.name or "申请公司" in form else app.company,
        "process_instance_id": str(instance_id),
        "process_code": process.process_code, "process_name": process.name,
        "title": raw.get("title") or "", "originator_userid": raw.get("originator_userid") or "",
        "originator_name": raw.get("originator_name") or "",
        "dept_name": raw.get("originator_dept_name") or raw.get("dept_name") or "",
        "status": raw.get("status") or "", "result": raw.get("result") or "",
        "amount": amount, "create_time": parse_datetime(raw.get("create_time")),
        "finish_time": parse_datetime(raw.get("finish_time")), "form_values": form, "raw": raw,
    }


@transaction.atomic
def save_approval(app, process, raw, instance_id, run=None, repair=False):
    if not instance_id:
        raise ValueError("同步必须使用列表接口返回的审批实例ID")
    data = instance_defaults(app, process, raw, instance_id)
    scope = approval_scope(app, process.process_code).select_for_update()
    canonical = list(scope.filter(process_instance_id=str(instance_id)))
    aliases = []
    business_id = raw.get("business_id")
    if business_id and str(business_id) != str(instance_id):
        # 只合并服务端明确给出的实例ID/业务编号对应关系，绝不按金额或收款人去重。
        aliases = [row for row in scope.filter(process_instance_id=str(business_id))
                   if str((row.raw or {}).get("business_id", "")) == str(business_id)]
    candidates = canonical + aliases
    if len(candidates) > 1 and not repair:
        raise ValueError(f"审批 {instance_id} 存在已证实的重复记录，请备份后运行组织修复")
    existing = next((row for row in canonical if row.company_id == data["company"].pk), None)
    existing = existing or (candidates[0] if candidates else None)
    created = existing is None
    previous = {"status": existing.status, "amount": existing.amount} if existing else {}
    if repair and existing:
        for duplicate in candidates:
            if duplicate.pk != existing.pk:
                duplicate.delete()
    if run:
        data["sync_run"] = run
    if existing:
        for key, value in data.items():
            setattr(existing, key, value)
        existing.save()
    else:
        existing = DingtalkApprovalInstance.objects.create(**data)
    return existing, created, previous
