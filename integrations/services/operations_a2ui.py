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


def _ratio(purchase, sales):
    if purchase is None or sales is None or not sales:
        return None
    return purchase / sales * 100


def _report_daily_amount(snapshot, name):
    """人员日报当日金额；无上报记录时为 None，不以金蝶金额回填。"""
    coverage = ((snapshot.data or {}).get(name) or {}).get("daily_coverage") or {}
    value = coverage.get("total_amount")
    return None if value is None else _decimal(value)


def _share_pie(purchase, sales):
    """采销构成环形图：两方都需有金额，负金额（退货）按 0 处理。"""
    if purchase is None or sales is None:
        return {"type": "pieChart", "data": []}, False
    rows = [
        {"x": label, "y": float(max(amount, Decimal(0)) / 10000)}
        for label, amount in (("采购", purchase), ("销售", sales))
    ]
    return {"type": "pieChart", "data": rows}, any(row["y"] > 0 for row in rows)


def build_operations_model(snapshot):
    from integrations.services.operations_summary import snapshot_operations

    data = snapshot_operations(snapshot)
    selected = [
        (name, label)
        for key, name, label, _ in BUSINESSES
        if snapshot.scope in ("BOTH", key) and name in (snapshot.data or {})
    ]
    if not selected:
        raise ValueError("没有可生成卡片的销售或采购快照数据。")
    summary = {"hasPurchase": False, "hasSales": False, "hasRatio": len(selected) == 2}
    report_amounts = {}
    kingdee_amounts = {}
    for name, label in selected:
        report_amount = _report_daily_amount(snapshot, name)
        kingdee_amount = data.get(name + "_daily")
        report_amounts[name] = report_amount
        kingdee_amounts[name] = (
            None if kingdee_amount is None else _decimal(kingdee_amount)
        )
        summary[name + "TotalText"] = (
            _money(data[name + "_total"])
            if data.get(name + "_total") is not None
            else "—"
        )
        summary[name + "DailyText"] = (
            _money(kingdee_amount) if kingdee_amount is not None else "—"
        )
        summary["report" + name.title() + "DailyText"] = (
            _money(report_amount) if report_amount is not None else "—"
        )
        summary["has" + name.title()] = True
    summary["shareText"] = _percent(data.get("share_total"))
    summary["reportShareDailyText"] = _percent(
        _ratio(report_amounts.get("purchase"), report_amounts.get("sales"))
    )
    summary["k3ShareDailyText"] = _percent(
        _ratio(kingdee_amounts.get("purchase"), kingdee_amounts.get("sales"))
    )
    report_pie, has_report_pie = _share_pie(
        report_amounts.get("purchase"), report_amounts.get("sales")
    )
    kingdee_pie, has_kingdee_pie = _share_pie(
        kingdee_amounts.get("purchase"), kingdee_amounts.get("sales")
    )
    has_share_pie = len(selected) == 2

    def metrics_values():
        """图片用原始数值：万元显示可压缩宽度，保证移动端四列都能看到。"""
        def number(value):
            return None if value is None else float(_decimal(value))

        rows = (
            ("当月累计", data.get("purchase_total"), data.get("sales_total")),
            ("人员日报", report_amounts.get("purchase"), report_amounts.get("sales")),
            ("金蝶 K3Cloud", kingdee_amounts.get("purchase"), kingdee_amounts.get("sales")),
        )
        output = []
        for label, raw_purchase, raw_sales in rows:
            purchase = None if raw_purchase is None else _decimal(raw_purchase)
            sales = None if raw_sales is None else _decimal(raw_sales)
            output.append(
                {
                    "label": label,
                    "purchase": number(purchase),
                    "sales": number(sales),
                    "share": number(_ratio(purchase, sales)),
                }
            )
        return {
            "hasPurchase": summary["hasPurchase"],
            "hasSales": summary["hasSales"],
            "hasShare": summary["hasRatio"],
            "rows": output,
        }

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
        "metricsValues": metrics_values(),
        "hasWarnings": bool(warnings),
        "warningText": "\n".join(warnings),
        "charts": {
            "trend": chart("trend_rows"),
            "month": chart("month_rows"),
            "reportShare": report_pie,
            "kingdeeShare": kingdee_pie,
        },
        "hasTrend": bool(data.get("trend_rows")),
        "hasMonth": bool(data.get("month_rows")),
        "hasReportShare": has_share_pie and has_report_pie,
        "hasKingdeeShare": has_share_pie and has_kingdee_pie,
        "monthCaption": f"{data.get('period_start','')}—{data.get('period_end','')} · 采购 / 销售，单位：万元",
        "trendCaption": f"{data.get('trend_start','')}—{snapshot.report_date.isoformat()} · 单位：万元",
        "shareCaption": "采购 / 销售金额构成 · 单位：万元",
        "scopeNote": "口径：月度与 K3Cloud 当日为金蝶有效采购入库 / 销售出库单，按业务日期汇总；人员日报为手工提交金额。退货不进入分布图；占比 = 采购 ÷ 销售，销售为 0 时显示 —。",
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
    return model


def build_operations_a2ui_messages(
    snapshot, template_path=None, metrics_image=None, *, link_url=None
):
    """metrics_image 为 {"light": mediaId, "dark": mediaId}；缺失时卡片用文字指标。

    link_url 有值时写进卡片底部的 Markdown 链接；为空则隐藏该组件，
    避免把模板里的占位地址发出去。
    """
    template_path = (
        Path(template_path)
        if template_path
        else Path(__file__).resolve().parents[2]
        / "docs/templates/operations_daily_report.a2ui.json"
    )
    frames = json.loads(template_path.read_text(encoding="utf-8"))
    model = build_operations_model(snapshot)
    model["hasMetricsImage"] = bool(metrics_image)
    surface = "operations-report-" + uuid4().hex
    for frame in frames:
        body = next(value for key, value in frame.items() if key != "version")
        body["surfaceId"] = surface
        if "updateDataModel" in frame:
            body["value"] = model
        # ImageList.images 只能写静态数组，media_id 要在发送前注入。
        if metrics_image and "updateComponents" in frame:
            for component in frame["updateComponents"]["components"]:
                if component.get("id") == "metrics-image":
                    component["images"] = [metrics_image["light"]]
        if "updateComponents" in frame:
            for component in frame["updateComponents"]["components"]:
                if component.get("id") != "report-link":
                    continue
                if link_url:
                    component["content"] = (
                        f"[查看完整在线报表（含图表与明细）]({link_url})\n\n"
                        "提示：链接在公司内网访问，请用公司电脑上的钉钉打开，"
                        "或让手机连接公司 Wi-Fi。"
                    )
                    component.pop("visible", None)
                else:
                    component["visible"] = False
    return frames
