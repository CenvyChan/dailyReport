"""采销经营汇总：金蝶业务日期金额，与手工月度对比表分别冻结入快照。"""

import copy
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from django.db.models import Sum, Count
from integrations.models import StockTransaction, StockTransactionLine
from reports.comparison import monthly_comparison

BUSINESSES = {"PURCHASE": ("purchase", "PURCHASE_IN"), "SALES": ("sales", "SALES_OUT")}


def _money(value):
    value = Decimal(str(value or 0))
    if not value.is_finite():
        raise ValueError("日报金额必须为有限数值。")
    return value


def _share(purchase, sales):
    return (
        str(
            (purchase / sales * 100).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        )
        if sales
        else None
    )


def _report_daily_amount(snapshot, name):
    """人员日报当日金额；与 A2UI 卡片同口径，没有提交记录时为 None。"""
    coverage = ((snapshot.data or {}).get(name) or {}).get("daily_coverage") or {}
    value = coverage.get("total_amount")
    return None if value is None else _money(value)


def _share_or_none(purchase, sales):
    if purchase is None or sales is None:
        return None
    return _share(_money(purchase), _money(sales))


def build_operations_summary(company, report_date, scope="BOTH"):
    month_start = report_date.replace(day=1)
    trend_start = report_date - timedelta(days=14)
    start = min(month_start, trend_start)
    selected = [key for key in BUSINESSES if scope in ("BOTH", key)]
    grouped = {}
    for key in selected:
        name, kind = BUSINESSES[key]
        grouped[name] = {
            row["biz_date"]: row
            for row in StockTransaction.objects.filter(
                company=company,
                business_type=kind,
                is_active=True,
                biz_date__gte=start,
                biz_date__lte=report_date,
            )
            .values("biz_date")
            .annotate(amount=Sum("total_amount"), count=Count("id"))
        }

    def rows(first):
        output = []
        for index in range((report_date - first).days + 1):
            day = first + timedelta(days=index)
            row = {"date": day.isoformat()}
            for name, values in grouped.items():
                row[name + "_amount"] = str(_money(values.get(day, {}).get("amount")))
                row[name + "_count"] = values.get(day, {}).get("count", 0)
            output.append(row)
        return output

    result = {
        "source": "KINGDEE",
        "period_start": month_start.isoformat(),
        "period_end": report_date.isoformat(),
        "trend_start": trend_start.isoformat(),
        "trend_rows": rows(trend_start),
        "month_rows": rows(month_start),
    }
    for name in grouped:
        result[name + "_total"] = str(
            sum(
                (_money(row[name + "_amount"]) for row in result["month_rows"]),
                Decimal(0),
            )
        )
        result[name + "_daily"] = result["month_rows"][-1][name + "_amount"]
        result[name + "_daily_count"] = result["month_rows"][-1][name + "_count"]
    result["share_total"] = (
        _share(_money(result.get("purchase_total")), _money(result.get("sales_total")))
        if len(selected) == 2
        else None
    )
    document_units = {}
    for row in (
        StockTransactionLine.objects.filter(
            transaction__company=company,
            transaction__is_active=True,
            transaction__business_type__in=[BUSINESSES[key][1] for key in selected],
            transaction__biz_date=report_date,
        )
        .values("transaction_id", "unit")
        .distinct()
    ):
        document_units.setdefault(row["transaction_id"], set()).add(
            row["unit"] or "未记录单位"
        )
    result["daily_documents"] = [
        {
            "business_type": key,
            "business_label": "采购" if key == "PURCHASE" else "销售",
            "bill_no": row["bill_no"],
            "date": row["biz_date"].isoformat(),
            "party_name": row["k3_party_name"] or "",
            "amount": str(_money(row["total_amount"])),
            "quantity": str(_money(row["total_quantity"])),
            "unit": " / ".join(sorted(document_units.get(row["id"], {"未记录单位"}))),
        }
        for key in selected
        for row in StockTransaction.objects.filter(
            company=company,
            is_active=True,
            business_type=BUSINESSES[key][1],
            biz_date=report_date,
        )
        .order_by("bill_no", "pk")
        .values(
            "id",
            "bill_no",
            "biz_date",
            "k3_party_name",
            "total_amount",
            "total_quantity",
        )
    ]
    return result


def build_monthly_comparison_snapshot(company, report_date):
    report = monthly_comparison(
        company=company, year=report_date.year, month=report_date.month
    )
    return {
        "source": "MANUAL_REPORTS",
        "year": report["year"],
        "month": report["month"],
        "purchase_total": str(report["purchase_total"]),
        "sales_total": str(report["sales_total"]),
        "share_total": (
            str(report["share_total"]) if report["share_total"] is not None else None
        ),
        "rows": [
            {
                **row,
                "date": row["date"].isoformat(),
                "purchase_amount": str(row["purchase_amount"]),
                "sales_amount": str(row["sales_amount"]),
                "share": str(row["share"]) if row["share"] is not None else None,
            }
            for row in report["rows"]
        ],
    }


def project_operations(summary, scope):
    result = copy.deepcopy(summary or {})
    hidden = [
        name for key, (name, _) in BUSINESSES.items() if scope not in ("BOTH", key)
    ]
    for name in hidden:
        for suffix in ("total", "daily", "daily_count"):
            result.pop(name + "_" + suffix, None)
        for key in ("trend_rows", "month_rows"):
            for row in result.get(key, []):
                row.pop(name + "_amount", None)
                row.pop(name + "_count", None)
    if "daily_documents" in result:
        result["daily_documents"] = [
            row
            for row in result["daily_documents"]
            if scope in ("BOTH", row["business_type"])
        ]
    if hidden:
        result["share_total"] = None
    return result


def snapshot_operations(snapshot):
    """只读冻结数据，不在渲染/重试时向数据库重新取数。旧快照需重新生成才有金蝶逐日数据。"""
    result = project_operations((snapshot.data or {}).get("operations"), snapshot.scope)
    if not result:
        result = {
            "source": "LEGACY_SNAPSHOT",
            "month_rows": [],
            "trend_rows": [],
            "share_total": None,
        }
    return result


def _quantity_text(value):
    if value is None:
        return "—"
    number = _money(value)
    rendered = format(number, ",.6f").rstrip("0").rstrip(".")
    return rendered or "0"


def _quantity_total(rows):
    if any(row.get("quantity") is None for row in rows):
        return None
    return str(sum((_money(row.get("quantity")) for row in rows), Decimal(0)))


def _quantity_unit(rows):
    units = {row.get("unit") or "未记录单位" for row in rows}
    if not units:
        return "—"
    if len(units) == 1:
        unit = next(iter(units))
        return "混合单位（未折算）" if " / " in unit else unit
    return "混合单位（未折算）"


def snapshot_detail_context(snapshot):
    """原版日报账簿和当日金蝶单据；即使无记录也保留分节与列。只读快照。"""
    ledgers = []
    manual_rows = []
    manual_pages = []
    for key in ("SALES", "PURCHASE"):
        if snapshot.scope not in ("BOTH", key):
            continue
        name, _ = BUSINESSES[key]
        label = "销售" if key == "SALES" else "采购"
        rows = [
            {**copy.deepcopy(row), "business_type": key, "business_label": label}
            for row in (snapshot.data or {})
            .get(name, {})
            .get("daily_coverage", {})
            .get("details", [])
        ]
        for row in rows:
            row["quantity_text"] = _quantity_text(row.get("quantity"))
            row["unit"] = row.get("unit") or "未记录单位"
        rows.sort(key=lambda row: (row.get("date", ""), row.get("report_id", 0)))
        ledger = {
            "label": label,
            "party_label": "客户名称" if key == "SALES" else "供应商名称",
            "rows": rows,
            "count": len(rows),
            "quantity_total": _quantity_total(rows),
            "quantity_total_text": _quantity_text(_quantity_total(rows)),
            "quantity_unit": _quantity_unit(rows),
            "total": str(sum((_money(row.get("amount")) for row in rows), Decimal(0))),
        }
        ledgers.append(ledger)
        manual_rows.extend(rows)
        for offset in range(0, max(len(rows), 1), 20):
            manual_pages.append(
                {
                    **ledger,
                    "rows": rows[offset : offset + 20],
                    "offset": offset,
                    "continuation": offset > 0,
                    "last": offset + 20 >= len(rows),
                }
            )
    operations = snapshot_operations(snapshot)
    documents = copy.deepcopy(operations.get("daily_documents", []))
    for row in documents:
        row["quantity_text"] = _quantity_text(row.get("quantity"))
        row["unit"] = row.get("unit") or "未记录单位"
    return {
        "manual_ledgers": ledgers,
        "manual_rows": manual_rows,
        "manual_quantity_total": _quantity_total(manual_rows),
        "manual_quantity_unit": _quantity_unit(manual_rows),
        "manual_total": str(
            sum((_money(row.get("amount")) for row in manual_rows), Decimal(0))
        ),
        "manual_pages": manual_pages,
        "kingdee_documents": documents,
        "kingdee_quantity_total": _quantity_total(documents),
        "kingdee_quantity_total_text": _quantity_text(_quantity_total(documents)),
        "kingdee_quantity_unit": _quantity_unit(documents),
        "kingdee_details_missing": "daily_documents" not in operations,
        "kingdee_document_total": str(
            sum((_money(row.get("amount")) for row in documents), Decimal(0))
        ),
        "kingdee_pages": [
            {
                "rows": documents[offset : offset + 20],
                "offset": offset,
                "continuation": offset > 0,
                "last": offset + 20 >= len(documents),
            }
            for offset in range(0, max(len(documents), 1), 20)
        ],
    }


CHART_LEFT = 52
CHART_RIGHT = 676
CHART_TOP = 28
CHART_BOTTOM = 168


def chart_geometry(rows, names):
    values = [_money(row.get(name + "_amount")) for row in rows for name in names]
    low = min([Decimal(0)] + values)
    high = max([Decimal(0)] + values)
    span = high - low or Decimal(1)

    def y(value):
        return round(
            CHART_TOP + float((high - value) / span) * (CHART_BOTTOM - CHART_TOP), 2
        )

    def x(index):
        return round(
            CHART_LEFT
            + index * (CHART_RIGHT - CHART_LEFT) / max(len(rows) - 1, 1),
            2,
        )

    series = []
    for name in names:
        points_list = [
            {
                "x": x(index),
                "y": y(_money(row.get(name + "_amount"))),
                "date": row["date"],
                "value": round(
                    float(_money(row.get(name + "_amount")) / 10000), 2
                ),
            }
            for index, row in enumerate(rows)
        ]
        series.append(
            {
                "name": name,
                "label": "采购" if name == "purchase" else "销售",
                "color": "#d97706" if name == "purchase" else "#2563eb",
                "points": " ".join(
                    f"{point['x']},{point['y']}" for point in points_list
                ),
                "points_list": points_list,
            }
        )

    tick_count = 5
    tick_span_wan = float((high - low) / 10000) / (tick_count - 1)
    if tick_span_wan >= 10:
        decimals = 0
    elif tick_span_wan >= 1:
        decimals = 1
    else:
        decimals = max(
            1, int(-math.floor(math.log10(max(tick_span_wan, 1e-9))))
        )
    y_ticks = []
    for index in range(tick_count):
        value = low + (high - low) * Decimal(index) / Decimal(tick_count - 1)
        y_ticks.append(
            {
                "y": y(value),
                "label": f"{float(value / 10000):,.{decimals}f}",
            }
        )

    x_tick_count = min(6, len(rows))
    x_labels = []
    for index in range(x_tick_count):
        row_index = round(
            index * (len(rows) - 1) / max(x_tick_count - 1, 1)
        )
        x_labels.append(
            {"x": x(row_index), "label": rows[row_index]["date"][5:]}
        )

    return {
        "series": series,
        "y_ticks": y_ticks,
        "x_labels": x_labels,
        "zero_y": y(Decimal(0)),
        "has_negative": low < 0,
        "has_data": bool(rows),
        "high": float(high / 10000),
        "low": float(low / 10000),
    }


def _donut(amounts):
    """采销构成环形图数据；采购或销售缺失/全为 0 时不展示。"""
    purchase = amounts.get("purchase")
    sales = amounts.get("sales")
    if purchase is None or sales is None:
        return {"has_data": False}
    purchase = max(_money(purchase), Decimal(0))
    sales = max(_money(sales), Decimal(0))
    total = purchase + sales
    if total <= 0:
        return {"has_data": False}
    circumference = 2 * math.pi * 46
    purchase_percent = float(purchase / total * 100)
    sales_percent = 100 - purchase_percent
    return {
        "has_data": True,
        "total": total,
        "circumference": round(circumference, 2),
        "segments": [
            {
                "label": "采购",
                "value": purchase,
                "percent": purchase_percent,
                "color": "#d97706",
                "length": round(circumference * purchase_percent / 100, 2),
                "offset": 0,
            },
            {
                "label": "销售",
                "value": sales,
                "percent": sales_percent,
                "color": "#2563eb",
                "length": round(circumference * sales_percent / 100, 2),
                "offset": round(-circumference * purchase_percent / 100, 2),
            },
        ],
    }


def monthly_analysis_context(snapshot, names):
    """本月采销分析：业务提报口径，与 /reports/comparison/ 同一份冻结数据。

    金额为字符串或 Decimal，模板按 money 过滤器统一格式化；缺失（旧快照）时
    has_data=False，由页面提示重新生成，绝不在渲染时回查数据库。
    """
    data = (snapshot.data or {}).get("monthly_comparison") or {}
    rows = []
    for row in data.get("rows") or []:
        rows.append(
            {
                "date": row.get("date", ""),
                "purchase": row.get("purchase_amount"),
                "sales": row.get("sales_amount"),
                "share": row.get("share"),
                "has_data": bool(row.get("has_data")),
                "over_full": bool(row.get("over_full")),
            }
        )
    totals = {
        "purchase": data.get("purchase_total"),
        "sales": data.get("sales_total"),
        "share": data.get("share_total"),
    }
    chart_rows = [
        {
            "date": row["date"],
            "purchase_amount": row["purchase"],
            "sales_amount": row["sales"],
        }
        for row in rows
    ]
    return {
        "has_data": bool(rows),
        "year": data.get("year"),
        "month": data.get("month"),
        "rows": rows,
        "totals": totals,
        "days_with_data": data.get("days_with_data")
        or sum(1 for row in rows if row["has_data"]),
        "chart": chart_geometry(chart_rows, names) if rows else {"has_data": False},
    }


def operations_context(snapshot):
    summary = snapshot_operations(snapshot)
    names = [
        name for key, (name, _) in BUSINESSES.items() if snapshot.scope in ("BOTH", key)
    ]
    metrics = [
        {
            "label": "当月" + ("采购" if name == "purchase" else "销售") + "日报合计",
            "value": summary.get(name + "_total"),
            "money": True,
        }
        for name in names
    ]
    if len(names) == 2:
        metrics.append(
            {"label": "合计占比", "value": summary.get("share_total"), "money": False}
        )
    daily = [
        {
            "label": "当日"
            + ("采购入库" if name == "purchase" else "销售出库")
            + "金额",
            "value": summary.get(name + "_daily"),
            "count": summary.get(name + "_daily_count", 0),
        }
        for name in names
    ]
    has_purchase = "purchase" in names
    has_sales = "sales" in names
    has_share = has_purchase and has_sales
    report_amounts = {
        name: _report_daily_amount(snapshot, name) for name in names
    }
    metric_rows = [
        {
            "label": "当月累计",
            "purchase": summary.get("purchase_total"),
            "sales": summary.get("sales_total"),
            "share": summary.get("share_total"),
        },
        {
            "label": "人员日报（当日）",
            "purchase": report_amounts.get("purchase"),
            "sales": report_amounts.get("sales"),
            "share": _share_or_none(
                report_amounts.get("purchase"), report_amounts.get("sales")
            ),
        },
        {
            "label": "金蝶 K3Cloud（当日）",
            "purchase": summary.get("purchase_daily"),
            "sales": summary.get("sales_daily"),
            "share": _share_or_none(
                summary.get("purchase_daily"), summary.get("sales_daily")
            ),
        },
    ]
    return {
        "snapshot": snapshot,
        **snapshot_detail_context(snapshot),
        "operations": summary,
        "summary_metrics": metrics,
        "daily_metrics": daily,
        "metric_rows": metric_rows,
        "has_purchase": has_purchase,
        "has_sales": has_sales,
        "has_share": has_share,
        "report_pie": _donut(report_amounts),
        "kingdee_pie": _donut(
            {
                "purchase": summary.get("purchase_daily"),
                "sales": summary.get("sales_daily"),
            }
        ),
        "month_chart": chart_geometry(summary.get("month_rows", []), names),
        "trend_chart": chart_geometry(summary.get("trend_rows", []), names),
        "monthly_analysis": monthly_analysis_context(snapshot, names),
    }
