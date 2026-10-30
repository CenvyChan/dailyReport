"""钉钉在线日报：面向手机浏览器的响应式 HTML。

与书册式 PDF 模板分开：书册固定 210mm 宽，适合打印，不适合手机横滑；
这里直接复用系统内报表的响应式布局（operations_summary.html）。
"""

from django.template.loader import render_to_string

from integrations.services.operations_summary import operations_context


def render_snapshot_public_html(snapshot) -> str:
    return render_to_string(
        "integrations/report_snapshot_public.html",
        operations_context(snapshot),
    )
