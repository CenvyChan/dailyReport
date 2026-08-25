from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from purchase.forms import PurchaseReceiptForm
from core.errors import MissingExchangeRate
from core.services import date_filter
from core.services.listing import paginate, search_queryset
from reports.services import summary_of
from core.services.permissions import (
    can_access_purchase,
    can_edit_receipt,
    editable_supplier_ids,
    is_administrator,
)
from core.responses import forbidden_page
from core.excel import read_rows
from core.uploads import error_workbook_response, import_response, read_upload
from purchase.importers import commit_purchase_import, preview_purchase_import
from purchase.services import (
    create_purchase_receipt,
    delete_purchase_receipt,
    purchase_queryset_for,
    update_purchase_receipt,
)


def _denied(request, *, as_page=True):
    """as_page=False 用于 fetch 调用的接口：前端要读 body，给它 HTML 会解析失败。"""
    reject = (lambda message: forbidden_page(request, message)) if as_page else HttpResponseForbidden
    if not can_access_purchase(request.user):
        return reject("无采购模块权限")
    if request.company is None:
        return reject("当前账号没有可进入的公司，请联系管理员授权")
    return None


@login_required
def receipt_list(request):
    denied = _denied(request)
    if denied:
        return denied
    queryset = search_queryset(
        purchase_queryset_for(request.user, request.company),
        request.GET.get("q"),
        ("supplier__name", "buyer__first_name", "buyer__username"),
    )
    # 默认只显示当天，口径与销售侧一致。
    dates = date_filter.resolve(request)
    queryset = date_filter.apply(queryset, dates, field="purchase_date")
    # 合计基于筛选后的全量而不是当前页，否则翻页时数字会跳。
    # 复用分析页的 summary_of，两处口径必须一致。
    totals = summary_of(queryset)
    page, querystring = paginate(request, queryset)
    # 逐行调 can_edit_receipt 会是每行一次查询，先把绑定的供应商 id 取成集合。
    editable = editable_supplier_ids(request.user, request.company)
    rows = [
        {"item": item, "can_edit": editable is None or item.supplier_id in editable}
        for item in page.object_list
    ]
    return render(
        request,
        "purchase/receipt_list.html",
        {
            "page": page,
            "rows": rows,
            "totals": totals,
            "receipts": page.object_list,
            "querystring": querystring,
            "search": request.GET.get("q", ""),
            "dates": dates,
            "start": dates["start"].isoformat() if dates["start"] else "",
            "end": dates["end"].isoformat() if dates["end"] else "",
            "can_import": is_administrator(request.user),
        },
    )


@login_required
def receipt_create(request):
    denied = _denied(request)
    if denied:
        return denied
    if request.method == "POST":
        form = PurchaseReceiptForm(request.POST, user=request.user, company=request.company)
        if not form.is_valid():
            return render(
                request,
                "purchase/receipt_form.html",
                {"form": form, "title": "新增采购日报"},
                status=400,
            )
        try:
            create_purchase_receipt(
                actor=request.user,
                company=request.company,
                data={**form.cleaned_data, "buyer": form.resolved_owner},
            )
        except MissingExchangeRate as exc:
            form.add_error(None, str(exc))
            return render(
                request,
                "purchase/receipt_form.html",
                {"form": form, "title": "新增采购日报"},
                status=400,
            )
        except PermissionError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        return redirect("purchase:receipt_list")
    return render(
        request,
        "purchase/receipt_form.html",
        {"form": PurchaseReceiptForm(user=request.user, company=request.company), "title": "新增采购日报"},
    )


@login_required
def receipt_edit(request, pk):
    denied = _denied(request)
    if denied:
        return denied
    receipt = get_object_or_404(purchase_queryset_for(request.user, request.company), pk=pk)
    # 可见范围已放开到全公司，写权限必须独立判断。403 而非 404：记录存在且看得到，
    # 只是不该由他改。
    if not can_edit_receipt(request.user, receipt):
        return forbidden_page(request, "这笔日报的供应商不在你的负责范围内，只有该供应商的采购员或管理员可以修改")
    if request.method == "POST":
        form = PurchaseReceiptForm(request.POST, instance=receipt, user=request.user, company=request.company)
        if not form.is_valid():
            return render(
                request,
                "purchase/receipt_form.html",
                {"form": form, "title": "编辑采购日报"},
                status=400,
            )
        try:
            update_purchase_receipt(
                actor=request.user,
                receipt=receipt,
                data={**form.cleaned_data, "buyer": form.resolved_owner},
            )
        except MissingExchangeRate as exc:
            form.add_error(None, str(exc))
            return render(
                request,
                "purchase/receipt_form.html",
                {"form": form, "title": "编辑采购日报"},
                status=400,
            )
        except PermissionError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        return redirect("purchase:receipt_list")
    return render(
        request,
        "purchase/receipt_form.html",
        {
            "form": PurchaseReceiptForm(instance=receipt, user=request.user, company=request.company),
            "title": "编辑采购日报",
        },
    )


@login_required
def receipt_delete(request, pk):
    denied = _denied(request)
    if denied:
        return denied
    if request.method != "POST":
        return JsonResponse({"error": "只允许使用 POST 请求"}, status=405)
    receipt = get_object_or_404(purchase_queryset_for(request.user, request.company), pk=pk)
    if not can_edit_receipt(request.user, receipt):
        return forbidden_page(request, "这笔日报的供应商不在你的负责范围内，只有该供应商的采购员或管理员可以删除")
    delete_purchase_receipt(actor=request.user, receipt=receipt)
    return redirect("purchase:receipt_list")


def _import_denied(request, *, as_page=True):
    reject = (lambda message: forbidden_page(request, message)) if as_page else HttpResponseForbidden
    if not is_administrator(request.user):
        return reject("仅管理员可导入采购数据")
    if request.company is None:
        return reject("请先选择公司后再导入")
    return None


@login_required
def import_page(request):
    denied = _import_denied(request)
    if denied:
        return denied
    return render(
        request,
        "imports/import_page.html",
        {
            "title": "采购数据导入",
            "preview_url": "purchase:import_preview",
            "commit_url": "purchase:import_commit",
            "errors_url": "purchase:import_errors_export",
            "template_kind": "purchase",
            "instructions": [
                f"数据将导入当前公司「{request.company.name}」，切换公司后重新导入不会互相覆盖。",
                "首个工作表字段为：供应商、采购员、采购类型、采购日期、数量、金额。",
                "也兼容销售样表中的客户名称、业务跟单、销售类型、出货日期列。",
                "国外采购需要先维护对应月份汇率，否则预览会提示缺少汇率。",
                "只有预览没有错误时才能正式导入，导入过程会记录操作日志。",
            ],
        },
    )


@login_required
def import_preview(request):
    denied = _import_denied(request, as_page=False)
    if denied:
        return denied

    def handler():
        content, _ = read_upload(request)
        preview = preview_purchase_import(content, company=request.company)
        return JsonResponse({
            "valid_row_count": preview.valid_row_count,
            "error_rows": preview.error_rows + (preview.rate_errors or []),
        })

    return import_response(handler)


@login_required
def import_commit(request):
    denied = _import_denied(request, as_page=False)
    if denied:
        return denied

    def handler():
        content, filename = read_upload(request)
        preview = preview_purchase_import(content, company=request.company)
        errors = preview.error_rows + (preview.rate_errors or [])
        if errors:
            return JsonResponse(
                {"valid_row_count": preview.valid_row_count, "error_rows": errors}, status=400
            )
        count = commit_purchase_import(
            preview, actor=request.user, company=request.company, source_file=filename
        )
        return JsonResponse({"imported": count})

    return import_response(handler)


@login_required
def import_errors_export(request):
    """把校验错误连同原始行导出成 Excel。

    重新解析一遍上传的文件而不是缓存预览结果：会话里存几千行原始数据代价大，
    而导出是低频操作，多解析一次可以接受。
    """
    denied = _import_denied(request, as_page=False)
    if denied:
        return denied

    def handler():
        content, _ = read_upload(request)
        preview = preview_purchase_import(content, company=request.company)
        content.seek(0)
        rows = read_rows(content)
        errors = preview.error_rows + (preview.rate_errors or [])
        return error_workbook_response(
            [("错误清单", rows, errors)],
            filename="采购导入错误清单.xlsx",
        )

    return import_response(handler)
