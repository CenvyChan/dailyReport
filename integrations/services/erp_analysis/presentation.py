"""为自包含 HTML 构造静态 SVG 趋势图，不加载 CDN。"""

from .common import number

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
    if not monthly:
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
    return {
        "lines": lines,
        "labels": [
            {"x": x, "text": row.get("month", row.get("name"))} for x, row in zip(x_values, monthly, strict=True)
        ],
        "zero_y": y(0),
        "high": f"{high:,.0f}",
        "low": f"{low:,.0f}",
    }
