"""报表快照视图：显示和下载报表。"""

import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from core.services.permissions import can_access_company
from integrations.models import ReportSnapshot
from integrations.services.snapshot_export import export_snapshot_to_excel

logger = logging.getLogger("integrations")


@login_required
def snapshot_view(request, snapshot_id):
    """查看报表快照。"""
    snapshot = get_object_or_404(ReportSnapshot, pk=snapshot_id)

    if not can_access_company(request.user, snapshot.company):
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

    return render(request, "integrations/report_snapshot.html", {"snapshot": snapshot})
