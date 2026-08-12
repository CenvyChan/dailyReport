from core.models import ExchangeRate
from core.services.audit import record_audit
from core.services.permissions import is_administrator


def _rate_snapshot(rate):
    return {"month": rate.month.isoformat(), "usd_to_cny": str(rate.usd_to_cny)}


def save_exchange_rate(*, actor, data, instance=None):
    if not is_administrator(actor):
        raise PermissionError("只有管理员可以维护汇率")
    if instance is None:
        rate = ExchangeRate.objects.create(**data)
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
