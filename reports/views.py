from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import render
from django.utils.http import url_has_allowed_host_and_scheme

from purchase.models import PurchaseReceipt
from core.responses import forbidden_page
from core.services.permissions import (
    can_view_comparison,
    can_view_purchase_reports,
    can_view_sales_reports,
)
from purchase.services import purchase_queryset_for
from reports.comparison import available_years, monthly_comparison
from reports.exporters import (
    ExportTooLarge,
    comparison_export_rows,
    purchase_export_rows,
    sales_export_rows,
    workbook_response,
)
from reports.services import (
    person_label,
    purchase_dashboard,
    purchase_filtered_queryset,
    preset_bounds,
    sales_dashboard,
    sales_filtered_queryset,
)
from sales.models import SalesShipment
from sales.services import sales_queryset_for


def _numeric(value):
    """下拉框传的是主键；手改 URL 传进非数字会让 .filter() 抛 ValueError，直接当没筛选。"""
    return value if value and value.isdigit() else None


def _iso_date(value):
    """同理，非法日期字符串会在 .filter() 里抛 ValidationError，当没筛选处理。"""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None


def _filters(request):
    filters = {
        "start": _iso_date(request.GET.get("start")),
        "end": _iso_date(request.GET.get("end")),
        "preset": request.GET.get("preset"),
        "person_id": _numeric(request.GET.get("person_id")),
        "counterpart_id": _numeric(request.GET.get("counterpart_id")),
        "business_type": request.GET.get("business_type"),
    }
    if filters["preset"] and not (filters["start"] or filters["end"]):
        start, end = preset_bounds(filters["preset"], timezone.localdate())
        filters["start"] = start.isoformat() if start else None
        filters["end"] = end.isoformat() if end else None
    return filters


def _denied(request, can_view, label, *, as_page=True):
    """as_page=False 用于看板的 JSON 接口：前端要读 body，给它 HTML 会解析失败。"""
    reject = (lambda message: forbidden_page(request, message)) if as_page else HttpResponseForbidden
    if not can_view(request.user):
        return reject(f"无{label}报表权限")
    if request.company is None:
        return reject("当前账号没有可进入的公司，请联系管理员授权")
    return None


@login_required
def sales_dashboard_view(request):
    denied = _denied(request, can_view_sales_reports, "销售")
    if denied:
        return denied
    dashboard = sales_dashboard(request.user, request.company, _filters(request))
    queryset = sales_queryset_for(request.user, request.company)
    return render(
        request,
        "reports/dashboard.html",
        {
            "title": "销售报表",
            "dashboard": dashboard,
            "filters": _filters(request),
            "people": [
                {"id": row["owner_id"], "label": row["label"]}
                for row in queryset.annotate(label=person_label("owner")).values("owner_id", "label").order_by("label").distinct()
            ],
            "counterparts": [
                {"id": row["customer_id"], "label": row["customer__name"]}
                for row in queryset.values("customer_id", "customer__name").order_by("customer__name").distinct()
            ],
            "type_choices": SalesShipment.SaleType.choices,
            "export_url_name": "reports:sales_export",
            "person_label": "负责人",
            "counterpart_label": "客户",
        },
    )


@login_required
def purchase_dashboard_view(request):
    denied = _denied(request, can_view_purchase_reports, "采购")
    if denied:
        return denied
    dashboard = purchase_dashboard(request.user, request.company, _filters(request))
    queryset = purchase_queryset_for(request.user, request.company)
    return render(
        request,
        "reports/dashboard.html",
        {
            "title": "采购报表",
            "dashboard": dashboard,
            "filters": _filters(request),
            "people": [
                {"id": row["buyer_id"], "label": row["label"]}
                for row in queryset.annotate(label=person_label("buyer")).values("buyer_id", "label").order_by("label").distinct()
            ],
            "counterparts": [
                {"id": row["supplier_id"], "label": row["supplier__name"]}
                for row in queryset.values("supplier_id", "supplier__name").order_by("supplier__name").distinct()
            ],
            "type_choices": PurchaseReceipt.PurchaseType.choices,
            "export_url_name": "reports:purchase_export",
            "person_label": "采购员",
            "counterpart_label": "供应商",
        },
    )


@login_required
def sales_dashboard_api(request):
    denied = _denied(request, can_view_sales_reports, "销售", as_page=False)
    if denied:
        return denied
    return JsonResponse(
        sales_dashboard(request.user, request.company, _filters(request)),
        safe=True,
        json_dumps_params={"ensure_ascii": False},
    )


@login_required
def purchase_dashboard_api(request):
    denied = _denied(request, can_view_purchase_reports, "采购", as_page=False)
    if denied:
        return denied
    return JsonResponse(
        purchase_dashboard(request.user, request.company, _filters(request)),
        safe=True,
        json_dumps_params={"ensure_ascii": False},
    )


def _safe_referer(request):
    """把 Referer 当返回链接用之前先校验，别让外站地址渲染成本站按钮。"""
    referer = request.META.get("HTTP_REFERER")
    if referer and url_has_allowed_host_and_scheme(
        referer, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return referer
    return None


def _export_response(request, filename, builder):
    """导出是普通链接跳转，不是 fetch，所以超限要回一个能看懂的页面，
    而不是 JSON 或裸文本。"""
    try:
        headers, rows = builder()
    except ExportTooLarge as error:
        return render(
            request,
            "reports/export_too_large.html",
            {"message": str(error), "back_url": _safe_referer(request)},
            status=400,
        )
    content = workbook_response(headers, rows)
    response = HttpResponse(
        content,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def sales_export(request):
    denied = _denied(request, can_view_sales_reports, "销售")
    if denied:
        return denied
    queryset = sales_filtered_queryset(request.user, request.company, _filters(request))
    return _export_response(
        request,
        f"sales-report-{request.company.code}.xlsx",
        lambda: sales_export_rows(queryset),
    )


@login_required
def purchase_export(request):
    denied = _denied(request, can_view_purchase_reports, "采购")
    if denied:
        return denied
    queryset = purchase_filtered_queryset(request.user, request.company, _filters(request))
    return _export_response(
        request,
        f"purchase-report-{request.company.code}.xlsx",
        lambda: purchase_export_rows(queryset),
    )


def _comparison_denied(request):
    """对比表是全公司口径的管理层报表（不按 owner 过滤），所以门禁比销售/采购
    报表更严：只放管理员和 report_viewer。

    不能用 can_view_*_reports 判断：那两个函数对「有客户/供应商归属」的普通
    业务员也返回 True（见 core/services/permissions.py 的 can_access_sales），
    而导入时会自动给业务员建归属，等于让业务员看到全公司采销汇总。
    """
    if not can_view_comparison(request.user):
        return forbidden_page(request, "对比表是全公司口径报表，需要管理员或报表查看权限")
    if request.company is None:
        return forbidden_page(request, "当前账号没有可进入的公司，请联系管理员授权")
    return None


def _requested_month(request, today):
    """年月从查询串取，非法值回退到本月，不报错。"""
    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
    except (TypeError, ValueError):
        return today.year, today.month
    if not 1 <= month <= 12 or not 2000 <= year <= 2999:
        return today.year, today.month
    return year, month


@login_required
def monthly_comparison_view(request):
    denied = _comparison_denied(request)
    if denied:
        return denied
    today = timezone.localdate()
    year, month = _requested_month(request, today)
    report = monthly_comparison(company=request.company, year=year, month=month)
    years = available_years(request.company) or [today.year]
    return render(
        request,
        "reports/comparison.html",
        {
            "report": report,
            "years": years,
            "months": range(1, 13),
        },
    )


@login_required
def monthly_comparison_export(request):
    denied = _comparison_denied(request)
    if denied:
        return denied
    today = timezone.localdate()
    year, month = _requested_month(request, today)
    report = monthly_comparison(company=request.company, year=year, month=month)
    content = workbook_response(*comparison_export_rows(report))
    response = HttpResponse(content, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = (
        f'attachment; filename="comparison-{request.company.code}-{year}{month:02d}.xlsx"'
    )
    return response
