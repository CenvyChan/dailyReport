from django.db import transaction

from core.models import (
    Customer,
    ExchangeRate,
    PurchaseAssignment,
    SalesAssignment,
    Supplier,
)
from core.services.audit import record_audit
from core.services.permissions import (
    can_access_purchase,
    can_access_sales,
    can_edit_customer,
    can_edit_supplier,
    is_administrator,
)


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


def _save_named(
    *, actor, company, model, data, instance, allowed, denial, assignment_model, owner_field, can_edit
):
    """客户/供应商的新增与编辑。

    除了角色校验，还要按绑定关系判断：只有负责这个客户的业务员才能改它的资料。
    此前只有 allowed(actor) 一道角色级校验，任何 sales 组成员可以编辑本公司
    任意客户，包括别人的。

    owners 是本次要绑定的业务员集合，保存时同步写 assignment 表。业务员自己
    新建客户时必须把自己绑上，否则建完立刻就看不见也改不了——绑定关系是可见
    和可写的唯一依据，而主数据维护路径此前完全不建绑定。
    """
    if not allowed(actor):
        raise PermissionError(denial)
    payload = dict(data)
    owners = payload.pop("owners", None)
    with transaction.atomic():
        if instance is None:
            obj = model.objects.create(company=company, **payload)
            action, before = "CREATE", {}
        else:
            obj = model.objects.get(pk=instance.pk)
            if obj.company_id != company.pk:
                raise PermissionError("不能修改其他公司的资料")
            if not can_edit(actor, obj):
                raise PermissionError(
                    "这条资料不在你的负责范围内，只有负责它的业务员或管理员可以修改"
                )
            before = _named_snapshot(obj)
            for field, value in payload.items():
                setattr(obj, field, value)
            obj.save()
            action = "UPDATE"
        if owners is not None:
            _sync_owners(
                obj=obj,
                owners=owners,
                actor=actor,
                assignment_model=assignment_model,
                owner_field=owner_field,
            )
    record_audit(actor=actor, instance=obj, action=action, before=before, after=_named_snapshot(obj))
    return obj


def _sync_owners(*, obj, owners, actor, assignment_model, owner_field):
    """把绑定关系同步成 owners。

    非管理员不能解除别人的绑定，也不能把自己摘掉——否则业务员可以把客户转走，
    转完自己就看不见了，而且相当于绕过「只有负责人能改」的限制去动别人的数据。
    管理员可以任意调整（含转移给他人）。
    """
    existing = set(
        assignment_model.objects.filter(**{owner_field: obj}).values_list("user_id", flat=True)
    )
    wanted = {user.pk for user in owners}
    if not is_administrator(actor):
        # 只允许新增，且必须保留自己
        wanted = wanted | existing | {actor.pk}
    to_add = wanted - existing
    to_remove = existing - wanted
    if to_remove:
        assignment_model.objects.filter(**{owner_field: obj}, user_id__in=to_remove).delete()
    if to_add:
        assignment_model.objects.bulk_create(
            [assignment_model(**{owner_field: obj}, user_id=user_id) for user_id in to_add]
        )


def save_customer(*, actor, company, data, instance=None):
    return _save_named(
        actor=actor, company=company, model=Customer, data=data, instance=instance,
        allowed=can_access_sales, denial="只有销售或管理员可以维护客户",
        assignment_model=SalesAssignment, owner_field="customer", can_edit=can_edit_customer,
    )


def save_supplier(*, actor, company, data, instance=None):
    return _save_named(
        actor=actor, company=company, model=Supplier, data=data, instance=instance,
        allowed=can_access_purchase, denial="只有采购或管理员可以维护供应商",
        assignment_model=PurchaseAssignment, owner_field="supplier", can_edit=can_edit_supplier,
    )
