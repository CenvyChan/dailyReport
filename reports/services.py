from datetime import date, timedelta
from decimal import Decimal

from django.db.models import DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce, TruncDay, TruncMonth

from purchase.services import purchase_queryset_for
from sales.services import sales_queryset_for


DECIMAL_ZERO = Value(Decimal("0"), output_field=DecimalField(max_digits=18, decimal_places=6))


def preset_bounds(preset, today):
    if preset == "month":
        return today.replace(day=1), today
    if preset == "week":
        return today - timedelta(days=today.weekday()), today
    if preset == "year":
        return today.replace(month=1, day=1), today
    return None, None


def _filters(queryset, filters, *, date_field, person_field, counterpart_field, type_field):
    if filters.get("start"):
        queryset = queryset.filter(**{f"{date_field}__gte": filters["start"]})
    if filters.get("end"):
        queryset = queryset.filter(**{f"{date_field}__lte": filters["end"]})
    for key, field in (("person_id", person_field), ("counterpart_id", counterpart_field), ("business_type", type_field)):
        if filters.get(key):
            queryset = queryset.filter(**{field: filters[key]})
    return queryset


def _summary(queryset):
    return queryset.aggregate(
        quantity=Coalesce(Sum("quantity"), Value(0)),
        cny_amount=Coalesce(Sum("original_amount", filter=Q(currency="CNY")), DECIMAL_ZERO),
        usd_amount=Coalesce(Sum("original_amount", filter=Q(currency="USD")), DECIMAL_ZERO),
        amount_cny=Coalesce(Sum("amount_cny"), DECIMAL_ZERO),
    )


def _trend(queryset, date_field, truncator):
    return list(
        queryset.values(period=truncator(date_field))
        .annotate(quantity=Sum("quantity"), amount_cny=Sum("amount_cny"))
        .order_by("period")
    )


def _rank(queryset, field):
    return list(
        queryset.annotate(label=F(field)).values("label")
        .annotate(quantity=Sum("quantity"), amount_cny=Sum("amount_cny"))
        .order_by("-amount_cny")[:10]
    )


def _share(queryset, field):
    return list(
        queryset.annotate(label=F(field)).values("label")
        .annotate(quantity=Sum("quantity"), amount_cny=Sum("amount_cny"))
        .order_by("-amount_cny")
    )


def sales_filtered_queryset(user, filters):
    return _filters(
        sales_queryset_for(user),
        filters,
        date_field="shipment_date",
        person_field="owner_id",
        counterpart_field="customer_id",
        type_field="sale_type",
    )


def sales_dashboard(user, filters):
    queryset = sales_filtered_queryset(user, filters)
    return {
        "summary": _summary(queryset),
        "daily_trend": _trend(queryset, "shipment_date", TruncDay),
        "monthly_trend": _trend(queryset, "shipment_date", TruncMonth),
        "type_share": _share(queryset, "sale_type"),
        "owner_rank": _rank(queryset, "owner__username"),
        "counterpart_rank": _rank(queryset, "customer__name"),
    }


def purchase_filtered_queryset(user, filters):
    return _filters(
        purchase_queryset_for(user),
        filters,
        date_field="purchase_date",
        person_field="buyer_id",
        counterpart_field="supplier_id",
        type_field="purchase_type",
    )


def purchase_dashboard(user, filters):
    queryset = purchase_filtered_queryset(user, filters)
    return {
        "summary": _summary(queryset),
        "daily_trend": _trend(queryset, "purchase_date", TruncDay),
        "monthly_trend": _trend(queryset, "purchase_date", TruncMonth),
        "type_share": _share(queryset, "purchase_type"),
        "owner_rank": _rank(queryset, "buyer__username"),
        "counterpart_rank": _rank(queryset, "supplier__name"),
    }
