from decimal import Decimal

from core.models import ExchangeRate, PurchaseAssignment
from core.services.audit import record_audit
from core.services.permissions import is_administrator
from purchase.models import PurchaseReceipt


def purchase_queryset_for(user):
    queryset = PurchaseReceipt.objects.select_related("supplier", "buyer")
    return queryset if is_administrator(user) else queryset.filter(buyer=user)


def _receipt_snapshot(receipt):
    return {
        "supplier_id": receipt.supplier_id,
        "buyer_id": receipt.buyer_id,
        "purchase_type": receipt.purchase_type,
        "purchase_date": receipt.purchase_date.isoformat(),
        "quantity": receipt.quantity,
        "currency": receipt.currency,
        "original_amount": str(receipt.original_amount),
        "exchange_rate": str(receipt.exchange_rate),
        "amount_cny": str(receipt.amount_cny),
        "source": receipt.source,
    }


def _amount_fields(*, purchase_type, purchase_date, original_amount):
    currency = "CNY" if purchase_type == PurchaseReceipt.PurchaseType.DOMESTIC else "USD"
    applied_rate = Decimal("1")
    if currency == "USD":
        applied_rate = ExchangeRate.objects.get(
            month=purchase_date.replace(day=1)
        ).usd_to_cny
    amount = Decimal(str(original_amount))
    return {
        "currency": currency,
        "exchange_rate": applied_rate,
        "amount_cny": amount * applied_rate,
    }


def _ensure_supplier_assignment(buyer, supplier):
    if not PurchaseAssignment.objects.filter(user=buyer, supplier=supplier).exists():
        raise PermissionError("供应商未分配给采购负责人")


def create_purchase_receipt(*, actor, data):
    payload = dict(data)
    buyer = payload.pop("buyer", actor)
    if buyer != actor and not is_administrator(actor):
        raise PermissionError("不能代替其他采购人员录入")
    _ensure_supplier_assignment(buyer, payload["supplier"])
    receipt = PurchaseReceipt.objects.create(
        buyer=buyer,
        **_amount_fields(
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
    _ensure_supplier_assignment(stored_receipt.buyer, payload["supplier"])
    before = _receipt_snapshot(stored_receipt)
    for field in ("supplier", "purchase_type", "purchase_date", "quantity", "original_amount"):
        setattr(receipt, field, payload[field])
    for field, value in _amount_fields(
        purchase_type=receipt.purchase_type,
        purchase_date=receipt.purchase_date,
        original_amount=receipt.original_amount,
    ).items():
        setattr(receipt, field, value)
    receipt.save()
    record_audit(
        actor=actor,
        instance=receipt,
        action="UPDATE",
        before=before,
        after=_receipt_snapshot(receipt),
    )
    return receipt


def delete_purchase_receipt(*, actor, receipt):
    record_audit(
        actor=actor,
        instance=receipt,
        action="DELETE",
        before=_receipt_snapshot(receipt),
        after={},
    )
    receipt.delete()
