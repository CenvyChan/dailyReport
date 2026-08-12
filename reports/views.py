from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render

from purchase.models import PurchaseReceipt
from core.services.permissions import can_view_purchase_reports, can_view_sales_reports
from purchase.services import purchase_queryset_for
from reports.exporters import purchase_export_rows, sales_export_rows, workbook_response
from reports.services import (
    purchase_dashboard,
    purchase_filtered_queryset,
    preset_bounds,
    sales_dashboard,
    sales_filtered_queryset,
)
from sales.models import SalesShipment
from sales.services import sales_queryset_for


def _filters(request):
    filters = {
        "start": request.GET.get("start"),
        "end": request.GET.get("end"),
        "preset": request.GET.get("preset"),
        "person_id": request.GET.get("person_id"),
        "counterpart_id": request.GET.get("counterpart_id"),
        "business_type": request.GET.get("business_type"),
    }
    if filters["preset"] and not (filters["start"] or filters["end"]):
        start, end = preset_bounds(filters["preset"], timezone.localdate())
        filters["start"] = start.isoformat() if start else None
        filters["end"] = end.isoformat() if end else None
    return filters


@login_required
def sales_dashboard_view(request):
    if not can_view_sales_reports(request.user):
        return HttpResponseForbidden("无销售报表权限")
    dashboard = sales_dashboard(request.user, _filters(request))
    queryset = sales_queryset_for(request.user)
    return render(
        request,
        "reports/dashboard.html",
        {
            "title": "销售报表",
            "dashboard": dashboard,
            "filters": _filters(request),
            "people": [
                {"id": row["owner_id"], "label": row["owner__username"]}
                for row in queryset.values("owner_id", "owner__username").order_by("owner__username").distinct()
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
    if not can_view_purchase_reports(request.user):
        return HttpResponseForbidden("无采购报表权限")
    dashboard = purchase_dashboard(request.user, _filters(request))
    queryset = purchase_queryset_for(request.user)
    return render(
        request,
        "reports/dashboard.html",
        {
            "title": "采购报表",
            "dashboard": dashboard,
            "filters": _filters(request),
            "people": [
                {"id": row["buyer_id"], "label": row["buyer__username"]}
                for row in queryset.values("buyer_id", "buyer__username").order_by("buyer__username").distinct()
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
    if not can_view_sales_reports(request.user):
        return HttpResponseForbidden("无销售报表权限")
    return JsonResponse(sales_dashboard(request.user, _filters(request)), safe=True, json_dumps_params={"ensure_ascii": False})


@login_required
def purchase_dashboard_api(request):
    if not can_view_purchase_reports(request.user):
        return HttpResponseForbidden("无采购报表权限")
    return JsonResponse(purchase_dashboard(request.user, _filters(request)), safe=True, json_dumps_params={"ensure_ascii": False})


@login_required
def sales_export(request):
    if not can_view_sales_reports(request.user):
        return HttpResponseForbidden("无销售报表权限")
    content = workbook_response(*sales_export_rows(sales_filtered_queryset(request.user, _filters(request))))
    response = HttpResponse(content, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="sales-report.xlsx"'
    return response


@login_required
def purchase_export(request):
    if not can_view_purchase_reports(request.user):
        return HttpResponseForbidden("无采购报表权限")
    content = workbook_response(*purchase_export_rows(purchase_filtered_queryset(request.user, _filters(request))))
    response = HttpResponse(content, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="purchase-report.xlsx"'
    return response
