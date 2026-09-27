"""系统数据 ↔ 金蝶库存发生 的逐日核对。仅统计有效(is_active)的金蝶单据。

系统侧：SalesShipment(销售) / PurchaseReceipt(采购) 的逐日 笔数/数量/金额(未税折人民币)。
金蝶侧：StockTransaction 的逐日 单据数/数量合计/金额合计。
两侧口径不同（系统是日报行、金蝶是单据；金蝶金额可能含税），故并列展示并给出差值，供人工判断漏录/多录。
"""

from calendar import monthrange
from datetime import date
from decimal import Decimal

from django.db.models import Count, DecimalField, Sum, Value
from django.db.models.functions import Coalesce

from purchase.models import PurchaseReceipt
from sales.models import SalesShipment
from integrations.models import BusinessType, StockTransaction

_AMT = DecimalField(max_digits=20, decimal_places=4)
_ZERO = Value(Decimal("0"), output_field=_AMT)

_SYSTEM = {
    BusinessType.SALES_OUT: (SalesShipment, "shipment_date"),
    BusinessType.PURCHASE_IN: (PurchaseReceipt, "purchase_date"),
}


def _system_daily(company, business_type, start, end):
    model, date_field = _SYSTEM[business_type]
    qs = model.objects.filter(company=company, **{f"{date_field}__gte": start, f"{date_field}__lte": end})
    rows = qs.values(date_field).annotate(
        count=Count("id"),
        quantity=Coalesce(Sum("quantity"), Value(Decimal("0"), output_field=DecimalField(max_digits=20, decimal_places=6))),
        amount=Coalesce(Sum("amount_cny"), _ZERO),
    )
    return {r[date_field]: r for r in rows}


def _kingdee_daily(company, business_type, start, end):
    qs = StockTransaction.objects.filter(
        company=company, business_type=business_type, is_active=True, biz_date__gte=start, biz_date__lte=end
    )
    rows = qs.values("biz_date").annotate(
        count=Count("id"),
        quantity=Coalesce(Sum("total_quantity"), Value(Decimal("0"), output_field=DecimalField(max_digits=20, decimal_places=6))),
        amount=Coalesce(Sum("total_amount"), _ZERO),
    )
    return {r["biz_date"]: r for r in rows}


def monthly_reconciliation(*, company, year, month, business_type):
    start = date(year, month, 1)
    end = date(year, month, monthrange(year, month)[1])
    system = _system_daily(company, business_type, start, end)
    kingdee = _kingdee_daily(company, business_type, start, end)

    rows = []
    totals = {"sys_count": 0, "sys_qty": Decimal("0"), "sys_amount": Decimal("0"),
              "k3_count": 0, "k3_qty": Decimal("0"), "k3_amount": Decimal("0")}
    for day in range(1, end.day + 1):
        current = date(year, month, day)
        s = system.get(current)
        k = kingdee.get(current)
        sys_count = s["count"] if s else 0
        sys_qty = s["quantity"] if s else Decimal("0")
        sys_amount = s["amount"] if s else Decimal("0")
        k3_count = k["count"] if k else 0
        k3_qty = k["quantity"] if k else Decimal("0")
        k3_amount = k["amount"] if k else Decimal("0")
        totals["sys_count"] += sys_count
        totals["sys_qty"] += sys_qty
        totals["sys_amount"] += sys_amount
        totals["k3_count"] += k3_count
        totals["k3_qty"] += k3_qty
        totals["k3_amount"] += k3_amount
        rows.append({
            "date": current,
            "sys_count": sys_count, "sys_qty": sys_qty, "sys_amount": sys_amount,
            "k3_count": k3_count, "k3_qty": k3_qty, "k3_amount": k3_amount,
            "count_diff": sys_count - k3_count,
            "qty_diff": sys_qty - k3_qty,
            "amount_diff": sys_amount - k3_amount,
            "has_data": bool(sys_count or k3_count),
        })
    totals["amount_diff"] = totals["sys_amount"] - totals["k3_amount"]
    totals["qty_diff"] = totals["sys_qty"] - totals["k3_qty"]
    totals["count_diff"] = totals["sys_count"] - totals["k3_count"]
    return {
        "company": company, "year": year, "month": month, "business_type": business_type,
        "rows": rows, "totals": totals,
    }


def available_years(company):
    years = set()
    for value in StockTransaction.objects.filter(company=company).dates("biz_date", "year"):
        years.add(value.year)
    for model, field in ((SalesShipment, "shipment_date"), (PurchaseReceipt, "purchase_date")):
        years.update(v.year for v in model.objects.filter(company=company).dates(field, "year"))
    return sorted(years, reverse=True)
