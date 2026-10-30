"""把卡片指标渲染成图片：桌面端与移动端都能看到完整数值。

A2UI 没有屏幕宽度函数，三列文字指标在移动端会被截断。图片走钉钉媒体库
（media_id），两端渲染器都能加载；ImageList 在桌面端还支持点击放大。

金额统一用万元：四列完整金额在移动端放不下，万元能把列宽压到可读范围。
"""

from html import escape

TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ margin: 0; background: transparent; }}
  .card {{
    display: inline-block; padding: 14px; border-radius: 12px;
    background: {background}; color: {text};
    font-family: "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
  }}
  .unit {{ font-size: 13px; color: {muted}; padding: 0 0 6px 4px; }}
  table {{ border-collapse: separate; border-spacing: 8px; margin: -8px; }}
  thead th {{
    font-size: 15px; font-weight: 400; color: {muted};
    text-align: left; padding: 0 2px 2px;
  }}
  tbody th {{
    font-size: 18px; text-align: left; padding-right: 6px; white-space: nowrap;
  }}
  td {{
    background: {surface}; border-radius: 8px; padding: 10px 14px;
    font-size: 32px; font-weight: 700; white-space: nowrap;
  }}
</style></head><body>
<div class="card" id="metrics-card">
<div class="unit">单位：万元</div>
<table>
<thead><tr><th></th>{headers}</tr></thead>
<tbody>
{rows}
</tbody>
</table>
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


def _wan(value):
    return "—" if value is None else f"{value / 10000:,.2f}"


def _percent(value):
    return "—" if value is None else f"{value:.1f}%"


def metrics_cells(model):
    """返回表头与每行的可见单元格；缺失模块整列省略。"""
    values = model.get("metricsValues") or {}
    has = (
        ("purchase", "采购", values.get("hasPurchase", False)),
        ("sales", "销售", values.get("hasSales", False)),
        ("share", "占比", values.get("hasShare", False)),
    )
    visible = [(key, title) for key, title, enabled in has if enabled]
    rows = []
    for row in values.get("rows", []):
        cells = [
            _percent(row.get(key)) if key == "share" else _wan(row.get(key))
            for key, _ in visible
        ]
        rows.append((row.get("label", ""), cells))
    return [title for _, title in visible], rows


def render_metrics_html(model, *, dark=False):
    palette = DARK if dark else LIGHT
    headers, rows = metrics_cells(model)
    header_html = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body_html = "\n".join(
        '<tr><th>{}</th>{}</tr>'.format(
            escape(label),
            "".join(f"<td>{escape(cell)}</td>" for cell in cells),
        )
        for label, cells in rows
    )
    return TEMPLATE.format(
        headers=header_html, rows=body_html, **palette
    )


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
