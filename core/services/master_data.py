from core.models import Customer, ExchangeRate, Supplier
from core.services.audit import record_audit
from core.services.permissions import can_access_purchase, can_access_sales, is_administrator


def _rate_snapshot(rate):
    return {"company_id": rate.company_id, "month": rate.month.isoformat(), "usd_to_cny": str(rate.usd_to_cny)}


def save_exchange_rate(*, actor, company, data, instance=None):
    if not is_administrator(actor):
        raise PermissionError("只有管理员可以维护汇率")
    if instance is None:
        rate = ExchangeRate.objects.create(company=company, **data)
        action = "CREATE"
        before = {}
    else:
        rate = ExchangeRate.objects.get(pk=instance.pk)
        before = _rate_snapshot(rate)
        rate.month = data["month"]
        rate.usd_to_cny = data["usd_to_cny"]
        rate.save()
        action = "UPDATE"
    record_audit(actor=actor, instance=rate, action=action, before=before, after=_rate_snapshot(rate))
    return rate


def _named_snapshot(instance):
    return {"company_id": instance.company_id, "name": instance.name, "is_active": instance.is_active}


def _save_named(*, actor, company, model, data, instance, allowed, denial):
    """客户/供应商的新增与编辑。销售能维护客户、采购能维护供应商，管理员两者皆可。"""
    if not allowed(actor):
        raise PermissionError(denial)
    if instance is None:
        obj = model.objects.create(company=company, **data)
        action, before = "CREATE", {}
    else:
        obj = model.objects.get(pk=instance.pk)
        if obj.company_id != company.pk:
            raise PermissionError("不能修改其他公司的资料")
        before = _named_snapshot(obj)
        for field, value in data.items():
            setattr(obj, field, value)
        obj.save()
        action = "UPDATE"
    record_audit(actor=actor, instance=obj, action=action, before=before, after=_named_snapshot(obj))
    return obj


def save_customer(*, actor, company, data, instance=None):
    return _save_named(
        actor=actor, company=company, model=Customer, data=data, instance=instance,
        allowed=can_access_sales, denial="只有销售或管理员可以维护客户",
    )


def save_supplier(*, actor, company, data, instance=None):
    return _save_named(
        actor=actor, company=company, model=Supplier, data=data, instance=instance,
        allowed=can_access_purchase, denial="只有采购或管理员可以维护供应商",
    )
