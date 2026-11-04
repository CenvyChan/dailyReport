"""付款申请报表快照：冻结汇总、签名公开链接与 PDF 渲染。

与采销日报快照（report_delivery.generate_report_snapshot）同思路：
同一公司、同一周期、同一审批模板只保留一条记录，定时任务重跑直接复用；
force 时原地重建并刷新 generated_at，让 PDF 缓存自然失效。
"""

import logging
from decimal import Decimal
from urllib.parse import quote

from django.conf import settings
from django.core import signing
from django.urls import reverse
from django.utils import timezone

from integrations.models import PaymentReportSnapshot

logger = logging.getLogger("integrations")

PAYMENT_SNAPSHOT_LINK_SALT = "payment-report-snapshot-link"


def _json_safe(value):
    """快照落库前把 Decimal 转字符串：JSONField 不认 Decimal，浮点会丢精度。"""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def build_payment_snapshot_data(data, report_type, period_info, company_name):
    """把 analyze_payment_applications 的输出整理成就绪落库的快照结构。"""
    return _json_safe(
        {
            "company_name": company_name,
            "sources": data.get("sources", []),
            "report_type": report_type,
            "period": {
                "label": period_info["label"],
                "start_date": period_info["start_date"].isoformat(),
                "end_date": period_info["end_date"].isoformat(),
            },
            "summary": data.get("summary") or {},
            "by_recipient": data.get("by_recipient") or [],
        }
    )


def generate_payment_snapshot(
    company,
    report_type,
    period_info,
    process_code,
    company_name,
    *,
    force=False,
    data=None,
):
    """生成或复用付款报表快照。

    Args:
        data: 已算好的 analyze_payment_applications 结果；为空时按周期重新查询。
              命令把自己算好的结果传进来，保证投递与快照口径完全一致。
    """
    if data is None:
        from integrations.services.payment_report import analyze_payment_applications

        data = analyze_payment_applications(
            company, period_info["start"], period_info["end"], process_code
        )
    snapshot_data = build_payment_snapshot_data(
        data, report_type, period_info, company_name
    )
    lookup = {
        "company": company,
        "report_type": report_type,
        "period_start": period_info["start_date"],
        "process_code": process_code,
    }
    existing = PaymentReportSnapshot.objects.filter(**lookup).first()
    if existing and not force:
        logger.info(
            "付款报表快照已存在：id=%s company=%s period=%s",
            existing.pk, company.code, period_info["label"],
        )
        return existing
    if existing:
        existing.period_end = period_info["end_date"]
        existing.period_label = period_info["label"]
        existing.data = snapshot_data
        existing.calculation_version = "v1"
        existing.generated_at = timezone.now()
        existing.save(
            update_fields=[
                "period_end", "period_label", "data",
                "calculation_version", "generated_at",
            ]
        )
        logger.info("付款报表快照已重建：id=%s", existing.pk)
        return existing
    snapshot = PaymentReportSnapshot.objects.create(
        **lookup,
        period_end=period_info["end_date"],
        period_label=period_info["label"],
        data=snapshot_data,
    )
    logger.info("付款报表快照已创建：id=%s", snapshot.pk)
    return snapshot


def payment_snapshot_url(snapshot) -> str:
    """生成免登录在线链接（签名 30 天有效），供钉钉群消息使用。"""
    token = signing.dumps({"snapshot": snapshot.pk}, salt=PAYMENT_SNAPSHOT_LINK_SALT)
    base = (
        getattr(settings, "PUBLIC_BASE_URL", "") or "http://172.16.77.80:8001"
    ).rstrip("/")
    path = reverse("integrations:payment_snapshot_public", args=[snapshot.pk])
    return f"{base}{path}?token={quote(token)}"


def render_payment_snapshot_pdf(snapshot) -> bytes:
    """把书册式模板渲染为 A4 PDF，内容与在线页来自同一份快照。"""
    from django.template.loader import render_to_string

    from integrations.services.payment_summary import payment_context
    from integrations.services.report_delivery import render_html_pdf

    html = render_to_string(
        "integrations/payment_snapshot_book.html", payment_context(snapshot)
    )
    return render_html_pdf(html)
