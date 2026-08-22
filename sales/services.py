from decimal import Decimal

from core.errors import MissingExchangeRate
from core.models import ExchangeRate, SalesAssignment
from core.services.audit import record_audit
from core.services.permissions import is_administrator
from sales.models import SalesShipment


def sales_queryset_for(user, company):
    if company is None:
        return SalesShipment.objects.none()
    queryset = SalesShipment.objects.filter(company=company).select_related("customer", "owner")
    return queryset if is_administrator(user) else queryset.filter(owner=user)


def _shipment_snapshot(shipment):
    return {
        "company_id": shipment.company_id,
        "customer_id": shipment.customer_id,
        "owner_id": shipment.owner_id,
        "sale_type": shipment.sale_type,
        "shipment_date": shipment.shipment_date.isoformat(),
        "quantity": str(shipment.quantity),
        "currency": shipment.currency,
        "original_amount": str(shipment.original_amount),
        "exchange_rate": str(shipment.exchange_rate),
        "amount_cny": str(shipment.amount_cny),
        "source": shipment.source,
    }


def _amount_fields(*, company, sale_type, shipment_date, original_amount):
    currency = "CNY" if sale_type == SalesShipment.SaleType.DOMESTIC else "USD"
    applied_rate = Decimal("1")
    if currency == "USD":
        month = shipment_date.replace(day=1)
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


def _ensure_customer_assignment(owner, customer, company):
    if customer.company_id != company.pk:
        raise PermissionError("客户不属于当前公司")
    if not SalesAssignment.objects.filter(user=owner, customer=customer).exists():
        raise PermissionError("客户未分配给销售负责人")


def create_sales_shipment(*, actor, company, data):
    payload = dict(data)
    # owner 由调用方按客户归属带出；缺省才退回操作人自己。
    owner = payload.pop("owner", None) or actor
    # 非管理员只能录到自己名下；管理员代录时 owner 是系统按归属算出来的，放行。
    if owner != actor and not is_administrator(actor):
        raise PermissionError("不能代替其他销售人员录入")
    _ensure_customer_assignment(owner, payload["customer"], company)
    shipment = SalesShipment.objects.create(
        owner=owner,
        company=company,
        **_amount_fields(
            company=company,
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
    # 换客户时负责人要跟着换，否则拿旧负责人去校验新客户的归属必然失败。
    owner = payload.pop("owner", None) or stored_shipment.owner
    if owner != stored_shipment.owner and not is_administrator(actor):
        raise PermissionError("不能把日报转给其他销售人员")
    _ensure_customer_assignment(owner, payload["customer"], stored_shipment.company)
    before = _shipment_snapshot(stored_shipment)
    shipment.owner = owner
    for field in ("customer", "sale_type", "shipment_date", "quantity", "original_amount"):
        setattr(shipment, field, payload[field])
    for field, value in _amount_fields(
        company=shipment.company,
        sale_type=shipment.sale_type,
        shipment_date=shipment.shipment_date,
        original_amount=shipment.original_amount,
    ).items():
        setattr(shipment, field, value)
    shipment.save()
    # 从库里读回，让 quantity 等 Decimal 字段按存储精度归一，
    # 否则审计日志里 before 是 "1.000"、after 是 "2"，无法直接比对。
    shipment.refresh_from_db()
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
