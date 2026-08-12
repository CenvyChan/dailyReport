from decimal import Decimal

from core.models import ExchangeRate, SalesAssignment
from core.services.audit import record_audit
from core.services.permissions import is_administrator
from sales.models import SalesShipment


def sales_queryset_for(user):
    queryset = SalesShipment.objects.select_related("customer", "owner")
    return queryset if is_administrator(user) else queryset.filter(owner=user)


def _shipment_snapshot(shipment):
    return {
        "customer_id": shipment.customer_id,
        "owner_id": shipment.owner_id,
        "sale_type": shipment.sale_type,
        "shipment_date": shipment.shipment_date.isoformat(),
        "quantity": shipment.quantity,
        "currency": shipment.currency,
        "original_amount": str(shipment.original_amount),
        "exchange_rate": str(shipment.exchange_rate),
        "amount_cny": str(shipment.amount_cny),
        "source": shipment.source,
    }


def _amount_fields(*, sale_type, shipment_date, original_amount):
    currency = "CNY" if sale_type == SalesShipment.SaleType.DOMESTIC else "USD"
    applied_rate = Decimal("1")
    if currency == "USD":
        applied_rate = ExchangeRate.objects.get(
            month=shipment_date.replace(day=1)
        ).usd_to_cny
    amount = Decimal(str(original_amount))
    return {
        "currency": currency,
        "exchange_rate": applied_rate,
        "amount_cny": amount * applied_rate,
    }


def _ensure_customer_assignment(owner, customer):
    if not SalesAssignment.objects.filter(user=owner, customer=customer).exists():
        raise PermissionError("客户未分配给销售负责人")


def create_sales_shipment(*, actor, data):
    payload = dict(data)
    owner = payload.pop("owner", actor)
    if owner != actor and not is_administrator(actor):
        raise PermissionError("不能代替其他销售人员录入")
    _ensure_customer_assignment(owner, payload["customer"])
    shipment = SalesShipment.objects.create(
        owner=owner,
        **_amount_fields(
            sale_type=payload["sale_type"],
            shipment_date=payload["shipment_date"],
            original_amount=payload["original_amount"],
        ),
        **payload,
    )
    record_audit(
        actor=actor,
        instance=shipment,
        action="IMPORT" if shipment.source == "HISTORY_IMPORT" else "CREATE",
        before={},
        after=_shipment_snapshot(shipment),
    )
    return shipment


def update_sales_shipment(*, actor, shipment, data):
    payload = dict(data)
    stored_shipment = SalesShipment.objects.get(pk=shipment.pk)
    _ensure_customer_assignment(stored_shipment.owner, payload["customer"])
    before = _shipment_snapshot(stored_shipment)
    for field in ("customer", "sale_type", "shipment_date", "quantity", "original_amount"):
        setattr(shipment, field, payload[field])
    for field, value in _amount_fields(
        sale_type=shipment.sale_type,
        shipment_date=shipment.shipment_date,
        original_amount=shipment.original_amount,
    ).items():
        setattr(shipment, field, value)
    shipment.save()
    record_audit(
        actor=actor,
        instance=shipment,
        action="UPDATE",
        before=before,
        after=_shipment_snapshot(shipment),
    )
    return shipment


def delete_sales_shipment(*, actor, shipment):
    record_audit(
        actor=actor,
        instance=shipment,
        action="DELETE",
        before=_shipment_snapshot(shipment),
        after={},
    )
    shipment.delete()
