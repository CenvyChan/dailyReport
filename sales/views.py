from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from core.errors import MissingExchangeRate
from core.services.listing import paginate, search_queryset
from core.services.permissions import can_access_sales, customer_queryset_for, is_administrator
from core.responses import forbidden_page
from core.excel import read_rows
from core.uploads import error_workbook_response, import_response, read_upload
from sales.forms import SalesShipmentForm
from sales.importers import commit_sales_import, preview_sales_import
from sales.services import (
    create_sales_shipment,
    delete_sales_shipment,
    sales_queryset_for,
    update_sales_shipment,
)


def _denied(request, *, as_page=True):
    """as_page=False 用于 fetch 调用的接口：前端要读 body，给它 HTML 会解析失败。"""
    reject = (lambda message: forbidden_page(request, message)) if as_page else HttpResponseForbidden
    if not can_access_sales(request.user):
        return reject("无销售模块权限")
    if request.company is None:
        return reject("当前账号没有可进入的公司，请联系管理员授权")
    return None


@login_required
def shipment_list(request):
    denied = _denied(request)
    if denied:
        return denied
    queryset = search_queryset(
        sales_queryset_for(request.user, request.company),
        request.GET.get("q"),
        ("customer__name", "owner__first_name", "owner__username"),
    )
    if request.GET.get("start"):
        queryset = queryset.filter(shipment_date__gte=request.GET["start"])
    if request.GET.get("end"):
        queryset = queryset.filter(shipment_date__lte=request.GET["end"])
    page, querystring = paginate(request, queryset)
    return render(
        request,
        "sales/shipment_list.html",
        {
            "page": page,
            "shipments": page.object_list,
            "querystring": querystring,
            "search": request.GET.get("q", ""),
            "start": request.GET.get("start", ""),
            "end": request.GET.get("end", ""),
            "can_import": is_administrator(request.user),
        },
    )


@login_required
def shipment_create(request):
    denied = _denied(request)
    if denied:
        return denied
    if request.method == "POST":
        form = SalesShipmentForm(request.POST, user=request.user, company=request.company)
        if not form.is_valid():
            return render(
                request,
                "sales/shipment_form.html",
                {"form": form, "title": "新增销售日报"},
                status=400,
            )
        try:
            create_sales_shipment(
                actor=request.user,
                company=request.company,
                data={**form.cleaned_data, "owner": form.resolved_owner},
            )
        except MissingExchangeRate as exc:
            form.add_error(None, str(exc))
            return render(
                request,
                "sales/shipment_form.html",
                {"form": form, "title": "新增销售日报"},
                status=400,
            )
        except PermissionError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        return redirect("sales:shipment_list")
    return render(
        request,
        "sales/shipment_form.html",
        {"form": SalesShipmentForm(user=request.user, company=request.company), "title": "新增销售日报"},
    )


@login_required
def shipment_edit(request, pk):
    denied = _denied(request)
    if denied:
        return denied
    shipment = get_object_or_404(sales_queryset_for(request.user, request.company), pk=pk)
    if request.method == "POST":
        form = SalesShipmentForm(request.POST, instance=shipment, user=request.user, company=request.company)
        if not form.is_valid():
            return render(
                request,
                "sales/shipment_form.html",
                {"form": form, "title": "编辑销售日报"},
                status=400,
            )
        try:
            update_sales_shipment(
                actor=request.user,
                shipment=shipment,
                data={**form.cleaned_data, "owner": form.resolved_owner},
            )
        except MissingExchangeRate as exc:
            form.add_error(None, str(exc))
            return render(
                request,
                "sales/shipment_form.html",
                {"form": form, "title": "编辑销售日报"},
                status=400,
            )
        except PermissionError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        return redirect("sales:shipment_list")
    return render(
        request,
        "sales/shipment_form.html",
        {
            "form": SalesShipmentForm(instance=shipment, user=request.user, company=request.company),
            "title": "编辑销售日报",
        },
    )


@login_required
def shipment_delete(request, pk):
    denied = _denied(request)
    if denied:
        return denied
    shipment = get_object_or_404(sales_queryset_for(request.user, request.company), pk=pk)
    if request.method != "POST":
        return JsonResponse({"error": "只允许使用 POST 请求"}, status=405)
    delete_sales_shipment(actor=request.user, shipment=shipment)
    return redirect("sales:shipment_list")


@login_required
def customer_options(request):
    denied = _denied(request, as_page=False)
    if denied:
        return denied
    return JsonResponse(
        {"customers": list(customer_queryset_for(request.user, request.company).values("id", "name"))}
    )


def _import_denied(request, *, as_page=True):
    reject = (lambda message: forbidden_page(request, message)) if as_page else HttpResponseForbidden
    if not is_administrator(request.user):
        return reject("仅管理员可导入销售数据")
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
            "title": "销售数据导入",
            "preview_url": "sales:import_preview",
            "commit_url": "sales:import_commit",
            "errors_url": "sales:import_errors_export",
            "template_kind": "sales",
            "instructions": [
                f"数据将导入当前公司「{request.company.name}」，切换公司后重新导入不会互相覆盖。",
                "文件需要包含数据表和汇率两个工作表。",
                "数据表字段为：客户名称、业务跟单、销售类型、出货日期、数量、金额。",
                "汇率表填写月份和美元兑人民币汇率；选择文件后先预览。",
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
        preview = preview_sales_import(content)
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
        preview = preview_sales_import(content)
        errors = preview.error_rows + (preview.rate_errors or [])
        if errors:
            return JsonResponse(
                {"valid_row_count": preview.valid_row_count, "error_rows": errors}, status=400
            )
        count = commit_sales_import(
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
        preview = preview_sales_import(content)
        content.seek(0)
        data_rows = read_rows(content, "数据表")
        content.seek(0)
        rate_rows = read_rows(content, "汇率")
        return error_workbook_response(
            [
                ("数据表", data_rows, preview.error_rows),
                ("汇率", rate_rows, preview.rate_errors or []),
            ],
            filename="销售导入错误清单.xlsx",
        )

    return import_response(handler)
