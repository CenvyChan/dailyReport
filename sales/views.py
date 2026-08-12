from io import BytesIO

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from core.services.permissions import can_access_sales, customer_queryset_for, is_administrator
from sales.forms import SalesShipmentForm
from sales.importers import commit_sales_import, preview_sales_import
from sales.models import SalesShipment
from sales.services import (
    create_sales_shipment,
    delete_sales_shipment,
    sales_queryset_for,
    update_sales_shipment,
)


@login_required
def shipment_list(request):
    if not can_access_sales(request.user):
        return HttpResponseForbidden("无销售模块权限")
    return render(
        request,
        "sales/shipment_list.html",
        {"shipments": sales_queryset_for(request.user), "can_import": is_administrator(request.user)},
    )


@login_required
def shipment_create(request):
    if not can_access_sales(request.user):
        return HttpResponseForbidden("无销售模块权限")
    if request.method == "POST":
        form = SalesShipmentForm(request.POST, user=request.user)
        if not form.is_valid():
            return render(
                request,
                "sales/shipment_form.html",
                {"form": form, "title": "新增销售日报"},
                status=400,
            )
        try:
            create_sales_shipment(actor=request.user, data=form.cleaned_data)
        except PermissionError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        return redirect("sales:shipment_list")
    return render(
        request,
        "sales/shipment_form.html",
        {"form": SalesShipmentForm(user=request.user), "title": "新增销售日报"},
    )


@login_required
def shipment_edit(request, pk):
    if not can_access_sales(request.user):
        return HttpResponseForbidden("无销售模块权限")
    shipment = get_object_or_404(sales_queryset_for(request.user), pk=pk)
    if request.method == "POST":
        form = SalesShipmentForm(request.POST, instance=shipment, user=request.user)
        if not form.is_valid():
            return render(
                request,
                "sales/shipment_form.html",
                {"form": form, "title": "编辑销售日报"},
                status=400,
            )
        try:
            update_sales_shipment(actor=request.user, shipment=shipment, data=form.cleaned_data)
        except PermissionError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        return redirect("sales:shipment_list")
    return render(
        request,
        "sales/shipment_form.html",
        {"form": SalesShipmentForm(instance=shipment, user=request.user), "title": "编辑销售日报"},
    )


@login_required
def shipment_delete(request, pk):
    if not can_access_sales(request.user):
        return HttpResponseForbidden("无销售模块权限")
    shipment = get_object_or_404(sales_queryset_for(request.user), pk=pk)
    if request.method != "POST":
        return JsonResponse({"error": "只允许使用 POST 请求"}, status=405)
    delete_sales_shipment(actor=request.user, shipment=shipment)
    return redirect("sales:shipment_list")


@login_required
def customer_options(request):
    if not can_access_sales(request.user):
        return HttpResponseForbidden("无销售模块权限")
    return JsonResponse({"customers": list(customer_queryset_for(request.user).values("id", "name"))})


@login_required
def import_page(request):
    if not is_administrator(request.user):
        return HttpResponseForbidden("仅管理员可导入销售数据")
    return render(
        request,
        "imports/import_page.html",
        {
            "title": "销售数据导入",
            "preview_url": "sales:import_preview",
            "commit_url": "sales:import_commit",
            "instructions": [
                "文件需要包含数据表和汇率两个工作表。",
                "数据表字段为：客户名称、业务跟单、销售类型、出货日期、数量、金额。",
                "汇率表填写月份和美元兑人民币汇率；选择文件后先预览。",
                "只有预览没有错误时才能正式导入，导入过程会记录操作日志。",
            ],
        },
    )


@login_required
def import_preview(request):
    if not is_administrator(request.user):
        return HttpResponseForbidden("仅管理员可导入")
    uploaded = request.FILES.get("file")
    if uploaded is None:
        return JsonResponse({"error": "请上传 Excel 文件"}, status=400)
    preview = preview_sales_import(BytesIO(uploaded.read()))
    return JsonResponse({"valid_row_count": preview.valid_row_count, "error_rows": preview.error_rows + (preview.rate_errors or [])})


@login_required
def import_commit(request):
    if not is_administrator(request.user):
        return HttpResponseForbidden("仅管理员可导入")
    uploaded = request.FILES.get("file")
    if uploaded is None:
        return JsonResponse({"error": "请上传 Excel 文件"}, status=400)
    content = uploaded.read()
    preview = preview_sales_import(BytesIO(content))
    errors = preview.error_rows + (preview.rate_errors or [])
    if errors:
        return JsonResponse({"valid_row_count": preview.valid_row_count, "error_rows": errors}, status=400)
    count = commit_sales_import(preview, actor=request.user, source_file=uploaded.name)
    return JsonResponse({"imported": count})
