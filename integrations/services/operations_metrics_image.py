"""把卡片指标渲染成图片：桌面端与移动端都能点开查看完整数值。

A2UI 没有屏幕宽度函数，三列指标在移动端会被压缩截断。图片走钉钉媒体库
（media_id），两端渲染器都能加载，且 Image 默认支持点击放大。
"""

from html import escape

TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ margin: 0; background: transparent; }}
  .card {{
    width: 620px; padding: 16px 18px; border-radius: 12px;
    background: {background}; color: {text};
    font-family: "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
    display: grid; grid-template-columns: 96px repeat({columns}, 1fr);
    gap: 8px 10px; align-items: stretch;
  }}
  .head {{ font-size: 14px; color: {muted}; padding: 0 2px 2px; }}
  .row-label {{ font-size: 17px; font-weight: 700; display: flex; align-items: center; }}
  .metric {{ background: {surface}; border-radius: 8px; padding: 10px 12px; }}
  .value {{ font-size: 30px; font-weight: 700; white-space: nowrap; }}
</style></head><body>
<div class="card" id="metrics-card">
{content}
</div></body></html>"""

LIGHT = {
    "background": "#ffffff",
    "text": "#1f2328",
    "muted": "#6e7781",
    "surface": "#f2f4f6",
}
DARK = {
    "background": "#1f2328",
    "text": "#e6edf3",
    "muted": "#9aa4af",
    "surface": "#2d333b",
}


def metrics_rows(model):
    """三行三列：当月累计、人员日报当日、金蝶当日。缺失模块显示 —。"""
    summary = model.get("summary") or {}
    purchase = summary.get("hasPurchase", False)
    sales = summary.get("hasSales", False)
    shared = summary.get("hasRatio", False)
    return [
        (
            "当月累计",
            summary.get("purchaseTotalText", "—") if purchase else None,
            summary.get("salesTotalText", "—") if sales else None,
            summary.get("shareText", "—") if shared else None,
        ),
        (
            "人员日报",
            summary.get("reportPurchaseDailyText", "—") if purchase else None,
            summary.get("reportSalesDailyText", "—") if sales else None,
            summary.get("reportShareDailyText", "—") if shared else None,
        ),
        (
            "金蝶 K3Cloud",
            summary.get("purchaseDailyText", "—") if purchase else None,
            summary.get("salesDailyText", "—") if sales else None,
            summary.get("k3ShareDailyText", "—") if shared else None,
        ),
    ]


def render_metrics_html(model, *, dark=False):
    palette = DARK if dark else LIGHT
    rows = metrics_rows(model)
    columns = sum(1 for value in rows[0][1:] if value is not None)
    headers = [
        title
        for title, value in (
            ("采购", rows[0][1]),
            ("销售", rows[0][2]),
            ("占比", rows[0][3]),
        )
        if value is not None
    ]
    cells = ["<div></div>" + "".join(f'<div class="head">{h}</div>' for h in headers)]
    for label, *values in rows:
        visible = [v for v in values if v is not None]
        cells.append(f'<div class="row-label">{escape(label)}</div>')
        for value in visible:
            cells.append(
                '<div class="metric">'
                f'<div class="value">{escape(str(value))}</div>'
                "</div>"
            )
    return TEMPLATE.format(columns=columns, content="\n".join(cells), **palette)


def render_metrics_image(model, *, dark=False):
    """渲染 PNG；调用方负责捕获渲染失败并降级为文字指标。"""
    from playwright.sync_api import sync_playwright

    html = render_metrics_html(model, dark=dark)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]
        )
        try:
            page = browser.new_page(device_scale_factor=2)
            page.set_content(html, wait_until="networkidle")
            return page.locator("#metrics-card").screenshot(type="png")
        finally:
            browser.close()
