from decimal import Decimal

from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce

from purchase.models import PurchaseReceipt
from sales.models import SalesShipment
from core.services.naming import display_name


DECIMAL_ZERO = Value(Decimal("0"), output_field=DecimalField(max_digits=18, decimal_places=6))
# 数量是 3 位小数的 DecimalField，Coalesce 的兜底值必须同类型，否则 Django 报 mixed types。
QUANTITY_ZERO = Value(Decimal("0"), output_field=DecimalField(max_digits=18, decimal_places=3))

SALES_HEADERS = ["出货日期", "客户", "负责人", "销售类型", "数量", "币种", "原币金额", "汇率快照", "折算人民币金额"]
PURCHASE_HEADERS = ["采购日期", "供应商", "采购员", "采购类型", "数量", "币种", "原币金额", "汇率快照", "折算人民币金额"]


def _summary(queryset):
    return queryset.aggregate(
        count=Count("id"),
        quantity=Coalesce(Sum("quantity"), QUANTITY_ZERO),
        cny_amount=Coalesce(Sum("original_amount", filter=Q(currency="CNY")), DECIMAL_ZERO),
        usd_amount=Coalesce(Sum("original_amount", filter=Q(currency="USD")), DECIMAL_ZERO),
        amount_cny=Coalesce(Sum("amount_cny"), DECIMAL_ZERO),
    )


def _rank(queryset, field, limit=5):
    return list(
        queryset.values(field)
        .annotate(quantity=Sum("quantity"), amount_cny=Sum("amount_cny"))
        .order_by("-amount_cny")[:limit]
    )


def _sales_rows(queryset):
    return [
        [
            item.shipment_date,
            item.customer.name,
            display_name(item.owner),
            item.get_sale_type_display(),
            item.quantity,
            item.currency,
            item.original_amount,
            item.exchange_rate,
            item.amount_cny,
        ]
        for item in queryset.select_related("customer", "owner").order_by("shipment_date", "id")
    ]


def _purchase_rows(queryset):
    return [
        [
            item.purchase_date,
            item.supplier.name,
            display_name(item.buyer),
            item.get_purchase_type_display(),
            item.quantity,
            item.currency,
            item.original_amount,
            item.exchange_rate,
            item.amount_cny,
        ]
        for item in queryset.select_related("supplier", "buyer").order_by("purchase_date", "id")
    ]


def build_daily_report(*, company, report_date, include_sales=True, include_purchase=True):
    """当天明细 + 当天/本月/本年汇总，全部限定在指定公司内。"""
    month_start = report_date.replace(day=1)
    year_start = report_date.replace(month=1, day=1)
    report = {
        "company": company,
        "report_date": report_date,
        "month_start": month_start,
        "year_start": year_start,
        "sales": None,
        "purchase": None,
    }

    if include_sales:
        base = SalesShipment.objects.filter(company=company)
        today = base.filter(shipment_date=report_date)
        report["sales"] = {
            "rows": _sales_rows(today),
            "headers": SALES_HEADERS,
            "today": _summary(today),
            "month": _summary(base.filter(shipment_date__gte=month_start, shipment_date__lte=report_date)),
            "year": _summary(base.filter(shipment_date__gte=year_start, shipment_date__lte=report_date)),
            "top_counterparts": _rank(today, "customer__name"),
        }

    if include_purchase:
        base = PurchaseReceipt.objects.filter(company=company)
        today = base.filter(purchase_date=report_date)
        report["purchase"] = {
            "rows": _purchase_rows(today),
            "headers": PURCHASE_HEADERS,
            "today": _summary(today),
            "month": _summary(base.filter(purchase_date__gte=month_start, purchase_date__lte=report_date)),
            "year": _summary(base.filter(purchase_date__gte=year_start, purchase_date__lte=report_date)),
            "top_counterparts": _rank(today, "supplier__name"),
        }

    return report


def has_any_data(report):
    return any(
        section is not None and section["today"]["count"]
        for section in (report["sales"], report["purchase"])
    )
