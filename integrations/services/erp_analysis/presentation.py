"""为自包含 HTML 构造静态 SVG 趋势图，不加载 CDN。"""

from math import pi

from .common import number, rounded

SERIES = {
    "purchase": [("amount", "订单金额"), ("settled", "已结算"), ("unsettled", "未结算")],
    "receivable": [("amount", "应收总额"), ("settled", "已收"), ("unsettled", "未收")],
    "inventory": [("in_amount", "收入金额"), ("out_amount", "发出金额"), ("end_amount", "期末金额")],
    "sales": [("out", "出库金额"), ("receivable", "应收金额"), ("settled", "实收金额")],
    "production": [("qty", "计划数量"), ("stockin", "入库数量"), ("remaining", "未入库数量")],
    "subcontract": [("qty", "计划数量"), ("stockin", "入库数量"), ("remaining", "未入库数量")],
}
COLORS = ("#4f46e5", "#0891b2", "#b45309")


def trend_chart(kind, data):
    monthly = [row for row in data["metrics"].get("monthly", []) if row.get("month", row.get("name")) != "未识别"]
    # 单月没有跨月趋势，避免绘制只有一个点的空折线图。
    if len(monthly) < 2:
        return None
    values = [float(number(row.get(key))) for key, _ in SERIES[kind] for row in monthly]
    low, high = min(0, min(values)), max(0, max(values))
    if high == low:
        high = low + 1

    def y(value):
        return round(195 - (float(number(value)) - low) / (high - low) * 165, 2)

    x_values = [round(65 + index * 760 / max(1, len(monthly) - 1), 2) for index in range(len(monthly))]
    lines = [
        {
            "label": label,
            "color": COLORS[index],
            "points": " ".join(f"{x},{y(row.get(key))}" for x, row in zip(x_values, monthly, strict=True)),
        }
        for index, (key, label) in enumerate(SERIES[kind])
    ]
    is_amount = kind in ("purchase", "receivable", "inventory", "sales")
    unit_label = "金额（元）" if is_amount else "数量（原始单位）"
    samples = []
    for index, (x, row) in enumerate(zip(x_values, monthly, strict=True)):
        month = row.get("month", row.get("name"))
        values = []
        for series_index, (key, label) in enumerate(SERIES[kind]):
            value = number(row.get(key))
            text = format(value, ",.2f") if is_amount else format(value, ",f")
            if not is_amount and "." in text:
                text = text.rstrip("0").rstrip(".")
            values.append({
                "label": label, "color": COLORS[series_index], "text": text,
                "y": y(value), "text_y": 44 + series_index * 19,
            })
        left = (x_values[index - 1] + x) / 2 if index else 65
        right = (x + x_values[index + 1]) / 2 if index + 1 < len(x_values) else 825
        samples.append({
            "month": month, "x": x, "values": values,
            "hit_x": round(left, 2), "hit_width": round(right - left, 2),
            "tooltip_x": max(8, min(x + 12, 662)),
            "description": f"{month}，{unit_label}；" + "；".join(f"{item['label']}：{item['text']}" for item in values),
        })
    return {
        "samples": samples,
        "unit_label": unit_label,
        "lines": lines,
        "labels": [
            {"x": x, "text": row.get("month", row.get("name"))} for x, row in zip(x_values, monthly, strict=True)
        ],
        "zero_y": y(0),
        "high": f"{high:,.0f}",
        "low": f"{low:,.0f}",
    }


CHART_COLORS = ("#4f46e5", "#0891b2", "#b45309", "#7c3aed", "#059669", "#db2777", "#64748b")


def display_number(value):
    return (
        format(number(value), "f").rstrip("0").rstrip(".")
        if number(value) % 1
        else format(number(value).quantize(number(1)), "f")
    )


def bar_chart(chart_id, title, values, note):
    values = [(str(label), number(value)) for label, value in values]
    low = min([number(0)] + [value for _, value in values])
    high = max([number(0)] + [value for _, value in values])
    scale = high - low or number(1)

    def x(value):
        return round(225 + float((value - low) / scale) * 510, 2)

    zero = x(number(0))
    items = []
    for index, (label, value) in enumerate(values):
        items.append(
            {
                "label": label,
                "value": display_number(value),
                "x": min(zero, x(value)),
                "width": round(abs(x(value) - zero), 2),
                "y": 18 + index * 44,
                "text_y": 36 + index * 44,
                "color": CHART_COLORS[index % len(CHART_COLORS)],
            }
        )
    return {
        "id": chart_id,
        "title": title,
        "type": "bar",
        "items": items,
        "note": note,
        "zero_x": zero,
        "height": max(88, len(items) * 44 + 28),
        "empty": not any(value for _, value in values),
    }


def donut_chart(chart_id, title, values, note):
    values = [(str(label), number(value)) for label, value in values]
    # 币种/金额负数不能塞进饼图；改为保留正负方向的条形图。
    if any(value < 0 for _, value in values):
        return bar_chart(chart_id, title, values, note + "；含负值，改用条形图保留原值。")
    total = sum((value for _, value in values), number(0))
    items, segments, offset = [], [], 0.0
    circumference = 2 * pi * 76
    for index, (label, value) in enumerate(values):
        share = value / total if total else number(0)
        item = {
            "label": label,
            "value": display_number(value),
            "ratio": format(rounded(share * 100, 1), "f"),
            "color": CHART_COLORS[index % len(CHART_COLORS)],
        }
        items.append(item)
        if value:
            length = float(share) * circumference
            segments.append(
                {
                    "label": label,
                    "value": item["value"],
                    "color": item["color"],
                    "dash": f"{length:.6f} {circumference - length:.6f}",
                    "offset": f"{-offset:.6f}",
                }
            )
            offset += length
    return {
        "id": chart_id,
        "title": title,
        "type": "donut",
        "items": items,
        "segments": segments,
        "total": display_number(total),
        "empty": not total,
        "note": note,
    }


def supporting_charts(kind, data):
    metrics = data["metrics"]
    summary = metrics.get("summary", {})

    def summary_values(columns):
        return [(label, summary.get(key, 0)) for key, label in columns]

    def ranking_values(rows, key):
        return [(row["name"], row.get(key, 0)) for row in rows[:10]]

    if kind == "purchase":
        delivery = metrics.get("delivery", {})
        return [
            bar_chart(
                "settlement",
                "应付与结算金额对比",
                summary_values((("payable", "应付金额"), ("settled", "已结算"), ("unsettled", "未结算"))),
                "采购报表金额口径。未结算逐行截零，图中三项是独立金额，不强制认定已结算＋未结算＝应付。",
            ),
            donut_chart(
                "delivery",
                "订单分录交付构成",
                [
                    (label, delivery.get(key, 0))
                    for key, label in (("exact_count", "已交齐"), ("short_count", "欠交"), ("over_count", "超交"))
                ],
                "分母为采购订单分录数，不使用采购报表展开行数；中心显示分录总数。",
            ),
            bar_chart(
                "supplier-debt",
                "供应商未结算金额 TOP 10",
                ranking_values(metrics.get("rankings", {}).get("supplier", []), "unsettled"),
                "取现有供应商未结算排行前 10 家；完整 TOP 50 见下方明细，不代表全体供应商的金额集中度。",
            ),
        ]
    if kind == "receivable":
        return [
            bar_chart(
                "receivable-settlement",
                "应收与收款计划金额",
                summary_values((("amount", "表头应收总额"), ("settled", "计划已收"), ("unsettled", "计划未收"))),
                "表头与收款计划来自不同字段；不强制平衡，差异仍见核对表。",
            ),
            bar_chart(
                "customer-debt",
                "客户未收金额 TOP 10",
                ranking_values(metrics.get("customers", []), "unsettled"),
                "客户未收取计划原值，不推算逾期账龄；负值原样保留。",
            ),
        ]
    if kind == "inventory":
        materials = sorted(metrics.get("materials", []), key=lambda item: number(item["end_amount"]), reverse=True)
        return [
            donut_chart(
                "stock-buckets",
                "库存覆盖分层 · 期末金额构成",
                [(row["name"], row["amount"]) for row in metrics.get("buckets", [])],
                "分层来自最新有数据期间的期末金额；覆盖月数不是库龄，负金额改用条形图。",
            ),
            bar_chart(
                "stock-materials",
                "期末库存金额 TOP 10 物料",
                [(row["name"], row["end_amount"]) for row in materials[:10]],
                "只使用最新有效期末库存，不累计多个期间的期末金额。",
            ),
        ]
    if kind == "sales":
        return [
            bar_chart(
                "sales-flow",
                "出库—应收—实收金额对比",
                summary_values((("out", "出库金额"), ("receivable", "应收金额"), ("settled", "实收金额"))),
                "原始金额可以超额，不绘制强制递减的漏斗；整体与分组结算率分母仍以正文为准。",
            ),
            bar_chart(
                "sales-customer-debt",
                "客户未结算金额 TOP 10",
                ranking_values(metrics.get("customers", []), "unsettled"),
                "未结算＝应收−实收，超收负值向零轴左侧展示，不截零。",
            ),
        ]
    if kind == "production":
        return [
            donut_chart(
                "production-status",
                "生产订单状态构成",
                [(row["name"], row["count"]) for row in metrics.get("status", [])],
                "按 ERP 状态编码汇总分录数；完工认定仍依据实际完工日期。",
            ),
            bar_chart(
                "workshop-backlog",
                "车间未入库数量 TOP 10",
                ranking_values(metrics.get("rankings", {}).get("workshop", []), "remaining"),
                "展示订单未入库数量，非产值或金额；不同物料数量需结合单位和明细阅读。",
            ),
        ]
    if kind == "subcontract":
        delivery = metrics.get("delivery", {})
        return [
            donut_chart(
                "subcontract-delivery",
                "已完工委外交付构成",
                [
                    (label, delivery.get(key, 0))
                    for key, label in (
                        ("on_time_count", "准时"),
                        ("late_count", "延期"),
                        ("no_plan_count", "缺计划日期"),
                    )
                ],
                "仅含已完工分录；图中包含缺计划日期，准时率的判定分母仍排除缺计划日期项。",
            ),
            bar_chart(
                "subcontract-wip",
                "供应商在制数量 TOP 10",
                ranking_values(metrics.get("wip_ranking", []), "wip"),
                "使用当前 ERP 在制原值，不是分析月末历史余额；负值向零轴左侧展示。",
            ),
        ]
    raise ValueError("未知的经营分析种类")


def descending_report_sections(data):
    """只调整日期明细/月份表的显示顺序，不改变趋势时间轴或金额排行。"""
    sections = []
    for section in data.get("sections", []):
        headers = section.get("headers", [])
        index = next(
            (headers.index(label) for label in ("申请日期", "订单日期", "业务日期", "月份") if label in headers), None
        )
        rows = section.get("rows", [])
        if index is not None:
            rows = sorted(rows, key=lambda row: str(row[index] or "").replace("/", "-"), reverse=True)
        sections.append({**section, "rows": rows})
    return {**data, "sections": sections}
