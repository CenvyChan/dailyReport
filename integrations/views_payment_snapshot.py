"""付款申请报表快照视图：在线页与 PDF/Excel 下载。

与采销日报快照（views_snapshot.py）同构：登录版给内部看，公开版靠签名
token 免登录访问，下载复用同一个 token，仍然只对单个快照有效。
"""

import logging
from datetime import date
from pathlib import Path
from urllib.parse import quote, urlencode

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from core.services.permissions import can_view_comparison
from integrations.models import PaymentReportSnapshot
from integrations.services.payment_excel import export_payment_excel_bytes
from integrations.services.payment_snapshot import (
    PAYMENT_SNAPSHOT_LINK_SALT,
    render_payment_snapshot_pdf,
)
from integrations.services.payment_summary import payment_context

logger = logging.getLogger("integrations")

XLSX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
# 模板结构变化时递增，避免继续命中旧缓存（与采销日报的 PDF_CACHE_VERSION 同理）。
PDF_CACHE_VERSION = "v1"


def _period_info(snapshot):
    """Excel 生成器需要 date 对象；快照里存的是 ISO 字符串。"""
    period = (snapshot.data or {}).get("period") or {}
    return {
        "label": snapshot.period_label,
        "start_date": date.fromisoformat(period["start_date"]),
        "end_date": date.fromisoformat(period["end_date"]),
    }


def _pdf_bytes(snapshot):
    """按需渲染 PDF，并按快照生成时间缓存，避免每次点下载都起一次 Chromium。"""
    cache_dir = Path(settings.BASE_DIR) / "data" / "payment_downloads"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{snapshot.pk}-{PDF_CACHE_VERSION}.pdf"
    if path.exists() and path.stat().st_mtime >= snapshot.generated_at.timestamp():
        return path.read_bytes()
    content = render_payment_snapshot_pdf(snapshot)
    path.write_bytes(content)
    return content


def _download_response(snapshot, kind):
    if kind == "excel":
        content = export_payment_excel_bytes(snapshot.data, _period_info(snapshot))
        extension, content_type = "xlsx", XLSX_CONTENT_TYPE
    elif kind == "pdf":
        content = _pdf_bytes(snapshot)
        extension, content_type = "pdf", "application/pdf"
    else:
        raise ValueError("未知下载类型")
    filename = (
        f"{snapshot.company.code}_付款申请{snapshot.get_report_type_display()}"
        f"_{snapshot.period_start:%Y%m%d}.{extension}"
    )
    response = HttpResponse(content, content_type=content_type)
    # 文件名含中文，用 RFC 5987 形式，避免部分客户端把中文截断。
    response["Content-Disposition"] = (
        f"attachment; filename*=UTF-8''{quote(filename)}"
    )
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


@login_required
def payment_snapshot_view(request, snapshot_id):
    """内部查看付款报表快照。"""
    snapshot = get_object_or_404(PaymentReportSnapshot, pk=snapshot_id)

    if not can_view_comparison(request.user, snapshot.company):
        from core.responses import forbidden_page

        return forbidden_page(request, "无权访问该公司的报表")

    kind = request.GET.get("download")
    if kind in ("pdf", "excel"):
        try:
            return _download_response(snapshot, kind)
        except Exception as e:
            logger.exception(
                "导出付款报表快照失败：snapshot_id=%s kind=%s", snapshot_id, kind
            )
            from django.contrib import messages

            messages.error(request, f"导出失败：{e}")

    return render(
        request,
        "integrations/payment_snapshot_public.html",
        {
            **payment_context(snapshot),
            "download_pdf_url": f"?{urlencode({'download': 'pdf'})}",
            "download_excel_url": f"?{urlencode({'download': 'excel'})}",
        },
    )


def payment_snapshot_public_view(request, snapshot_id):
    """钉钉消息里的在线付款报表：签名链接有效期内无需登录即可查看。"""
    token = request.GET.get("token", "")
    try:
        payload = signing.loads(
            token, salt=PAYMENT_SNAPSHOT_LINK_SALT, max_age=60 * 60 * 24 * 30
        )
    except signing.BadSignature:
        return HttpResponseForbidden("链接已失效，请联系管理员重新发送报表。")
    if int(payload.get("snapshot", 0)) != snapshot_id:
        return HttpResponseForbidden("链接与报表不匹配。")
    snapshot = get_object_or_404(PaymentReportSnapshot, pk=snapshot_id)

    kind = request.GET.get("download")
    if kind in ("pdf", "excel"):
        try:
            return _download_response(snapshot, kind)
        except Exception:
            logger.exception(
                "公开链接导出失败：snapshot_id=%s kind=%s", snapshot_id, kind
            )
            return HttpResponse("下载失败，请稍后重试。", status=500)

    base = reverse("integrations:payment_snapshot_public", args=[snapshot.pk])
    download_pdf_url = f"{base}?{urlencode({'token': token, 'download': 'pdf'})}"
    download_excel_url = f"{base}?{urlencode({'token': token, 'download': 'excel'})}"
    from django.template.loader import render_to_string

    response = HttpResponse(
        render_to_string(
            "integrations/payment_snapshot_public.html",
            {
                **payment_context(snapshot),
                "download_pdf_url": download_pdf_url,
                "download_excel_url": download_excel_url,
            },
        ),
        content_type="text/html; charset=utf-8",
    )
    # 报表含经营数据，禁止搜索引擎和预览机器人索引。
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Cache-Control"] = "private, max-age=300"
    return response
