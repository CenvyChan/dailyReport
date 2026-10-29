"""采购/销售日报 A2UI：既有快照口径、原生图表及群内容范围隔离。"""

import copy
import json
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

BUSINESSES = (
    ("SALES", "sales", "销售", "客户"),
    ("PURCHASE", "purchase", "采购", "供应商"),
)


def filter_snapshot_for_contents(snapshot, content_types):
    """只创建只读副本，绝不修改数据库快照或将未勾选模块放入附件。"""
    allowed = set(content_types or ())
    available = {key for key, name, _, _ in BUSINESSES if name in (snapshot.data or {})}
    if snapshot.scope in ("SALES", "PURCHASE"):
        available &= {snapshot.scope}
    selected = available & allowed
    if not selected:
        raise ValueError("该群没有选择此快照中的销售或采购内容。")
    filtered = copy.copy(snapshot)
    filtered.data = copy.deepcopy(snapshot.data or {})
    for key, name, _, _ in BUSINESSES:
        if key not in selected:
            filtered.data.pop(name, None)
    filtered.scope = "BOTH" if len(selected) == 2 else next(iter(selected))
    filtered.data["scope"] = filtered.scope
    if "corrections" in filtered.data:
        labels = selected | {
            label for key, _, label, _ in BUSINESSES if key in selected
        }
        filtered.data["corrections"] = [
            row
            for row in filtered.data["corrections"]
            if row.get("affected_report") in labels
        ]
    from integrations.services.operations_summary import project_operations

    if "operations" in filtered.data:
        filtered.data["operations"] = project_operations(
            filtered.data["operations"], filtered.scope
        )
    comparison = filtered.data.get("monthly_comparison")
    if comparison and filtered.scope != "BOTH":
        hidden = "sales" if filtered.scope == "PURCHASE" else "purchase"
        comparison.pop(hidden + "_total", None)
        comparison["share_total"] = None
        for row in comparison.get("rows", []):
            row.pop(hidden + "_amount", None)
            row["share"] = None
    return filtered


def _decimal(value):
    value = Decimal(str(value if value is not None else 0))
    if not value.is_finite():
        raise ValueError("日报金额必须为有限数值。")
    return value


def _money(value):
    return f"¥{_decimal(value):,.2f}"


def _percent(value):
    return "—" if value is None else f"{_decimal(value):.1f}%"


def build_operations_a2ui_messages(snapshot, template_path=None):
    from integrations.services.operations_summary import snapshot_operations

    template_path = (
        Path(template_path)
        if template_path
        else Path(__file__).resolve().parents[2]
        / "docs/templates/operations_daily_report.a2ui.json"
    )
    frames = json.loads(template_path.read_text(encoding="utf-8"))
    data = snapshot_operations(snapshot)
    selected = [
        (name, label)
        for key, name, label, _ in BUSINESSES
        if snapshot.scope in ("BOTH", key) and name in (snapshot.data or {})
    ]
    if not selected:
        raise ValueError("没有可生成卡片的销售或采购快照数据。")
    summary = {"hasPurchase": False, "hasSales": False, "hasRatio": len(selected) == 2}
    for name, label in selected:
        summary[name + "TotalText"] = (
            _money(data[name + "_total"])
            if data.get(name + "_total") is not None
            else "—"
        )
        summary[name + "DailyText"] = (
            _money(data[name + "_daily"])
            if data.get(name + "_daily") is not None
            else "—"
        )
        summary["has" + name.title()] = True
    summary["shareText"] = _percent(data.get("share_total"))

    def chart(key):
        return {
            "type": "lineChart",
            "data": [
                {
                    "x": row["date"][5:],
                    "y": float(_decimal(row.get(name + "_amount")) / 10000),
                    "type": label,
                }
                for row in data.get(key, [])
                for name, label in selected
            ],
        }

    warnings = list(snapshot.sync_warnings or [])
    if not snapshot.is_complete and not warnings:
        warnings.append("同步尚未覆盖报表日期，数据可能不完整。")
    if data.get("source") != "KINGDEE":
        warnings.append(
            "历史快照尚未包含金蝶逐日汇总，请重新生成；不以手工日报替代金蝶金额。"
        )
    model = {
        "companyName": snapshot.company.name,
        "reportTitle": (
            "采购 · 销售汇总日报" if len(selected) == 2 else selected[0][1] + "经营日报"
        ),
        "period": snapshot.report_date.isoformat(),
        "periodLabel": "报表日期：" + snapshot.report_date.isoformat(),
        "dataLabel": "金蝶 K3Cloud",
        "summary": summary,
        "hasWarnings": bool(warnings),
        "warningText": "\n".join(warnings),
        "charts": {"trend": chart("trend_rows"), "month": chart("month_rows")},
        "hasTrend": bool(data.get("trend_rows")),
        "hasMonth": bool(data.get("month_rows")),
        "monthCaption": f"{data.get('period_start','')}—{data.get('period_end','')} · 采购 / 销售，单位：万元",
        "trendCaption": f"{data.get('trend_start','')}—{snapshot.report_date.isoformat()} · 单位：万元",
        "scopeNote": "口径：金蝶有效采购入库 / 销售出库单，按业务日期汇总，退货保留负数；合计占比 = 当月采购 ÷ 当月销售，销售为 0 时显示 —。图表金额单位为万元；月度统计截至报表日。",
        "reportMeta": {
            "dataMode": "live",
            "source": "KINGDEE",
            "currency": "CNY",
            "chartAmountUnit": "万元",
            "scope": snapshot.scope,
        },
    }
    model["deliverySummary"] = (
        f"{snapshot.company.name} · {model['reportTitle']} · {snapshot.report_date.isoformat()} · "
        + "；".join(
            label + " " + summary[name + "DailyText"] for name, label in selected
        )
    )
    surface = "operations-report-" + uuid4().hex
    for frame in frames:
        body = next(value for key, value in frame.items() if key != "version")
        body["surfaceId"] = surface
        if "updateDataModel" in frame:
            body["value"] = model
    return frames
