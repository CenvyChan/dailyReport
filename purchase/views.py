from io import BytesIO

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from purchase.forms import PurchaseReceiptForm
from core.services.permissions import can_access_purchase, is_administrator
from purchase.importers import commit_purchase_import, preview_purchase_import
from purchase.services import (
    create_purchase_receipt,
    delete_purchase_receipt,
    purchase_queryset_for,
    update_purchase_receipt,
)


@login_required
def receipt_list(request):
    if not can_access_purchase(request.user):
        return HttpResponseForbidden("无采购模块权限")
    return render(
        request,
        "purchase/receipt_list.html",
        {"receipts": purchase_queryset_for(request.user), "can_import": is_administrator(request.user)},
    )


@login_required
def receipt_create(request):
    if not can_access_purchase(request.user):
        return HttpResponseForbidden("无采购模块权限")
    if request.method == "POST":
        form = PurchaseReceiptForm(request.POST, user=request.user)
        if not form.is_valid():
            return render(
                request,
                "purchase/receipt_form.html",
                {"form": form, "title": "新增采购日报"},
                status=400,
            )
        try:
            create_purchase_receipt(actor=request.user, data=form.cleaned_data)
        except PermissionError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        return redirect("purchase:receipt_list")
    return render(
        request,
        "purchase/receipt_form.html",
        {"form": PurchaseReceiptForm(user=request.user), "title": "新增采购日报"},
    )


@login_required
def receipt_edit(request, pk):
    if not can_access_purchase(request.user):
        return HttpResponseForbidden("无采购模块权限")
    receipt = get_object_or_404(purchase_queryset_for(request.user), pk=pk)
    if request.method == "POST":
        form = PurchaseReceiptForm(request.POST, instance=receipt, user=request.user)
        if not form.is_valid():
            return render(
                request,
                "purchase/receipt_form.html",
                {"form": form, "title": "编辑采购日报"},
                status=400,
            )
        try:
            update_purchase_receipt(actor=request.user, receipt=receipt, data=form.cleaned_data)
        except PermissionError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        return redirect("purchase:receipt_list")
    return render(
        request,
        "purchase/receipt_form.html",
        {"form": PurchaseReceiptForm(instance=receipt, user=request.user), "title": "编辑采购日报"},
    )


@login_required
def receipt_delete(request, pk):
    if not can_access_purchase(request.user):
        return HttpResponseForbidden("无采购模块权限")
    receipt = get_object_or_404(purchase_queryset_for(request.user), pk=pk)
    if request.method != "POST":
        return JsonResponse({"error": "只允许使用 POST 请求"}, status=405)
    delete_purchase_receipt(actor=request.user, receipt=receipt)
    return redirect("purchase:receipt_list")


@login_required
def import_page(request):
    if not is_administrator(request.user):
        return HttpResponseForbidden("仅管理员可导入采购数据")
    return render(
        request,
        "imports/import_page.html",
        {
            "title": "采购数据导入",
            "preview_url": "purchase:import_preview",
            "commit_url": "purchase:import_commit",
            "instructions": [
                "首个工作表字段为：供应商、采购员、采购类型、采购日期、数量、金额。",
                "也兼容销售样表中的客户名称、业务跟单、销售类型、出货日期列。",
                "国外采购需要先维护对应月份汇率，否则预览会提示缺少汇率。",
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
    preview = preview_purchase_import(BytesIO(uploaded.read()))
    return JsonResponse({"valid_row_count": preview.valid_row_count, "error_rows": preview.error_rows + (preview.rate_errors or [])})


@login_required
def import_commit(request):
    if not is_administrator(request.user):
        return HttpResponseForbidden("仅管理员可导入")
    uploaded = request.FILES.get("file")
    if uploaded is None:
        return JsonResponse({"error": "请上传 Excel 文件"}, status=400)
    preview = preview_purchase_import(BytesIO(uploaded.read()))
    errors = preview.error_rows + (preview.rate_errors or [])
    if errors:
        return JsonResponse({"valid_row_count": preview.valid_row_count, "error_rows": errors}, status=400)
    count = commit_purchase_import(preview, actor=request.user, source_file=uploaded.name)
    return JsonResponse({"imported": count})
