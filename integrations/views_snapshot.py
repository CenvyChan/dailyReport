"""报表快照视图：显示和下载报表。"""

import logging

from django.contrib.auth.decorators import login_required
from django.core import signing
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, render

from core.services.permissions import can_view_comparison
from integrations.models import ReportSnapshot
from integrations.services.report_delivery import (
    SNAPSHOT_LINK_SALT,
    render_snapshot_book_html,
)
from integrations.services.snapshot_export import export_snapshot_to_excel

logger = logging.getLogger("integrations")


@login_required
def snapshot_view(request, snapshot_id):
    """查看报表快照。"""
    snapshot = get_object_or_404(ReportSnapshot, pk=snapshot_id)

    if not can_view_comparison(request.user, snapshot.company):
        from core.responses import forbidden_page
        return forbidden_page(request, "无权访问该公司的报表")

    # 支持 Excel 下载
    if request.GET.get("download") == "excel":
        try:
            excel_bytes = export_snapshot_to_excel(snapshot)
            filename = f"{snapshot.company.code}_{snapshot.report_date}_report.xlsx"
            response = HttpResponse(
                excel_bytes,
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            return response
        except Exception as e:
            logger.exception("导出报表快照失败：snapshot_id=%s", snapshot_id)
            from django.contrib import messages
            messages.error(request, f"导出失败：{e}")

    return render(
        request,
        "integrations/report_snapshot.html",
        {"snapshot": snapshot, "standalone": False},
    )


def snapshot_public_view(request, snapshot_id):
    """钉钉消息里的在线日报：签名链接有效期内无需登录即可查看。

    只开放只读的 HTML 快照，不暴露列表、下载或重新生成入口；链接带 30 天
    时效，且只对单个快照有效。
    """
    token = request.GET.get("token", "")
    try:
        payload = signing.loads(token, salt=SNAPSHOT_LINK_SALT, max_age=60 * 60 * 24 * 30)
    except signing.BadSignature:
        return HttpResponseForbidden("链接已失效，请联系管理员重新发送日报。")
    if int(payload.get("snapshot", 0)) != snapshot_id:
        return HttpResponseForbidden("链接与报表不匹配。")
    snapshot = get_object_or_404(ReportSnapshot, pk=snapshot_id)
    response = HttpResponse(
        render_snapshot_book_html(snapshot),
        content_type="text/html; charset=utf-8",
    )
    # 报表含经营数据，禁止搜索引擎和预览机器人索引。
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Cache-Control"] = "private, max-age=300"
    return response
