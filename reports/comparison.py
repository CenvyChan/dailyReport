"""采购入库金额与销售金额对比表。

口径（业务方确认）：FNS / NBHH 的销售数据都以**未税**为准，不做含税换算。
- 采购金额：直接取折算人民币金额。
- 销售金额：直接取折算人民币金额（外币按录入当月汇率快照折算）。
- 每天占比 = 采购 / 销售。销售为 0 时占比留空（不写 0，避免误读成"当天没采购"）。
"""

from calendar import monthrange
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Sum

from purchase.models import PurchaseReceipt
from sales.models import SalesShipment


CENTS = Decimal("0.01")
PERCENT = Decimal("0.0001")


def _money(value):
    return (value or Decimal("0")).quantize(CENTS, rounding=ROUND_HALF_UP)


def _daily_totals(queryset, date_field, amount_field="amount_cny"):
    return {
        row[date_field]: row["total"]
        for row in queryset.values(date_field).annotate(total=Sum(amount_field))
    }


def month_bounds(year, month):
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def monthly_comparison(*, company, year, month):
    """返回该月逐日的采购金额、销售金额与占比，以及月度合计。金额均为未税口径。"""
    start, end = month_bounds(year, month)

    purchases = _daily_totals(
        PurchaseReceipt.objects.filter(company=company, purchase_date__gte=start, purchase_date__lte=end),
        "purchase_date",
    )
    sales = _daily_totals(
        SalesShipment.objects.filter(company=company, shipment_date__gte=start, shipment_date__lte=end),
        "shipment_date",
    )

    rows = []
    purchase_total = Decimal("0")
    sales_total = Decimal("0")
    for day in range(1, end.day + 1):
        current = date(year, month, day)
        purchase_amount = _money(purchases.get(current))
        # 逐日先取整到分，保证逐日之和与月度合计完全一致。
        sales_amount = _money(sales.get(current))
        purchase_total += purchase_amount
        sales_total += sales_amount
        share = _share(purchase_amount, sales_amount)
        rows.append(
            {
                "date": current,
                "purchase_amount": purchase_amount,
                "sales_amount": sales_amount,
                "share": share,
                # 模板里比较 Decimal 与数字不可靠，标记在这里算好。
                "over_full": share is not None and share > Decimal("100"),
                "has_data": bool(purchase_amount or sales_amount),
            }
        )

    return {
        "company": company,
        "year": year,
        "month": month,
        "rows": rows,
        "purchase_total": purchase_total,
        "sales_total": sales_total,
        "share_total": _share(purchase_total, sales_total),
        "days_with_data": sum(1 for row in rows if row["has_data"]),
    }


def _share(purchase_amount, sales_amount):
    """占比 = 采购 / 销售，用百分数表示。销售为 0 时返回 None（界面显示 '-'）。"""
    if not sales_amount:
        return None
    return ((purchase_amount / sales_amount) * Decimal("100")).quantize(PERCENT, rounding=ROUND_HALF_UP)


def available_years(company):
    """有数据的年份，用于年份下拉。"""
    years = set()
    for model, field in ((SalesShipment, "shipment_date"), (PurchaseReceipt, "purchase_date")):
        years.update(
            value.year
            for value in model.objects.filter(company=company).dates(field, "year")
        )
    return sorted(years, reverse=True)
