from decimal import Decimal

from core.errors import MissingExchangeRate
from core.models import ExchangeRate, PurchaseAssignment
from core.services.audit import record_audit
from core.services.permissions import can_edit_receipt, is_administrator, is_read_only
from purchase.models import PurchaseReceipt


def purchase_queryset_for(user, company):
    """本公司全部采购日报。口径与 sales_queryset_for 一致：公司内不再按 buyer
    过滤，写权限由 can_edit_receipt 按供应商绑定关系单独判断。"""
    if company is None:
        return PurchaseReceipt.objects.none()
    return PurchaseReceipt.objects.filter(company=company).select_related("supplier", "buyer")


def _receipt_snapshot(receipt):
    return {
        "company_id": receipt.company_id,
        "supplier_id": receipt.supplier_id,
        "buyer_id": receipt.buyer_id,
        "purchase_type": receipt.purchase_type,
        "purchase_date": receipt.purchase_date.isoformat(),
        "quantity": str(receipt.quantity),
        "currency": receipt.currency,
        "original_amount": str(receipt.original_amount),
        "exchange_rate": str(receipt.exchange_rate),
        "amount_cny": str(receipt.amount_cny),
        "source": receipt.source,
    }


def _amount_fields(*, company, purchase_type, purchase_date, original_amount):
    currency = "CNY" if purchase_type == PurchaseReceipt.PurchaseType.DOMESTIC else "USD"
    applied_rate = Decimal("1")
    if currency == "USD":
        month = purchase_date.replace(day=1)
        rate = ExchangeRate.objects.filter(company=company, month=month).first()
        if rate is None:
            raise MissingExchangeRate(company, month)
        applied_rate = rate.usd_to_cny
    amount = Decimal(str(original_amount))
    return {
        "currency": currency,
        "exchange_rate": applied_rate,
        "amount_cny": amount * applied_rate,
    }


def _ensure_supplier_assignment(buyer, supplier, company):
    if supplier.company_id != company.pk:
        raise PermissionError("供应商不属于当前公司")
    if not PurchaseAssignment.objects.filter(user=buyer, supplier=supplier).exists():
        raise PermissionError("供应商未分配给采购负责人")


def create_purchase_receipt(*, actor, company, data):
    if is_read_only(actor):
        raise PermissionError("报表查看角色不能录入日报")
    payload = dict(data)
    # buyer 由调用方按供应商归属带出；缺省才退回操作人自己。
    buyer = payload.pop("buyer", None) or actor
    # 非管理员只能录到自己名下；管理员代录时 buyer 是系统按归属算出来的，放行。
    if buyer != actor and not is_administrator(actor):
        raise PermissionError("不能代替其他采购人员录入")
    _ensure_supplier_assignment(buyer, payload["supplier"], company)
    receipt = PurchaseReceipt.objects.create(
        buyer=buyer,
        company=company,
        **_amount_fields(
            company=company,
            purchase_type=payload["purchase_type"],
            purchase_date=payload["purchase_date"],
            original_amount=payload["original_amount"],
        ),
        **payload,
    )
    record_audit(
        actor=actor,
        instance=receipt,
        action="IMPORT" if receipt.source == "HISTORY_IMPORT" else "CREATE",
        before={},
        after=_receipt_snapshot(receipt),
    )
    return receipt


def update_purchase_receipt(*, actor, receipt, data):
    payload = dict(data)
    stored_receipt = PurchaseReceipt.objects.get(pk=receipt.pk)
    # 此前 actor 完全不参与判断，写权限靠视图层 queryset 取不到就 404 兜着；
    # 可见范围放开后那道守卫失效，校验必须落到服务层。
    if not can_edit_receipt(actor, stored_receipt):
        raise PermissionError("只能修改自己负责供应商的日报")
    # 换供应商时负责人要跟着换，否则拿旧负责人去校验新供应商的归属必然失败。
    buyer = payload.pop("buyer", None) or stored_receipt.buyer
    if buyer != stored_receipt.buyer and not is_administrator(actor):
        raise PermissionError("不能把日报转给其他采购人员")
    _ensure_supplier_assignment(buyer, payload["supplier"], stored_receipt.company)
    before = _receipt_snapshot(stored_receipt)
    receipt.buyer = buyer
    for field in ("supplier", "purchase_type", "purchase_date", "quantity", "original_amount"):
        setattr(receipt, field, payload[field])
    for field, value in _amount_fields(
        company=receipt.company,
        purchase_type=receipt.purchase_type,
        purchase_date=receipt.purchase_date,
        original_amount=receipt.original_amount,
    ).items():
        setattr(receipt, field, value)
    receipt.save()
    # 从库里读回，让 quantity 等 Decimal 字段按存储精度归一，
    # 否则审计日志里 before 是 "1.000"、after 是 "2"，无法直接比对。
    receipt.refresh_from_db()
    record_audit(
        actor=actor,
        instance=receipt,
        action="UPDATE",
        before=before,
        after=_receipt_snapshot(receipt),
    )
    return receipt


def delete_purchase_receipt(*, actor, receipt):
    # 删除此前零校验，谁拿到实例都能删。
    if not can_edit_receipt(actor, receipt):
        raise PermissionError("只能删除自己负责供应商的日报")
    record_audit(
        actor=actor,
        instance=receipt,
        action="DELETE",
        before=_receipt_snapshot(receipt),
        after={},
    )
    receipt.delete()
