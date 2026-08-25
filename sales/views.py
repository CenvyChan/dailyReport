from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from core.errors import MissingExchangeRate
from core.services import date_filter
from core.services.listing import filter_by, filter_by_name, paginate, search_queryset
from reports.services import person_label, summary_of
from core.services.permissions import (
    can_access_sales,
    can_edit_shipment,
    customer_queryset_for,
    editable_customer_ids,
    is_administrator,
)
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
    scoped = sales_queryset_for(request.user, request.company)
    # 负责人/客户/币种改成各自的下拉：一个大文本框搜「高」会同时命中「高席」和
    # 「高新科技」，用户分不清筛到了什么。候选取自本公司实际出现过的值。
    options = {
        "people": [
            {"id": row["owner_id"], "label": row["label"]}
            for row in scoped.annotate(label=person_label("owner"))
            .values("owner_id", "label")
            .order_by("label")
            .distinct()
        ],
        "counterparts": [
            {"id": row["customer_id"], "label": row["customer__name"]}
            for row in scoped.values("customer_id", "customer__name")
            .order_by("customer__name")
            .distinct()
        ],
        "currencies": list(
            scoped.values_list("currency", flat=True).order_by("currency").distinct()
        ),
    }
    queryset = filter_by(scoped, request, {"owner": "owner_id", "currency": "currency"})
    # 客户走名称匹配：下拉换成 input + datalist 后提交的是名称而不是 id
    queryset = filter_by_name(queryset, request, "counterpart", options["counterparts"], "customer_id")
    queryset = search_queryset(
        queryset,
        request.GET.get("q"),
        ("customer__name", "owner__first_name", "owner__username"),
    )
    dates = date_filter.resolve(request)
    queryset = date_filter.apply(queryset, dates, field="shipment_date")
    # 合计基于筛选后的全量而不是当前页，否则翻页时数字会跳。
    # 复用分析页的 summary_of，两处口径必须一致，否则用户会怀疑哪个是对的。
    totals = summary_of(queryset)
    page, querystring = paginate(request, queryset)
    # 逐行调 can_edit_shipment 会是每行一次查询，先把绑定的客户 id 取成集合。
    # 只读角色和无绑定的人拿到空集，按钮就都不渲染。
    editable = editable_customer_ids(request.user, request.company)
    rows = [
        {"item": item, "can_edit": editable is None or item.customer_id in editable}
        for item in page.object_list
    ]
    return render(
        request,
        "sales/shipment_list.html",
        {
            "page": page,
            "rows": rows,
            "shipments": page.object_list,
            "totals": totals,
            "querystring": querystring,
            "search": request.GET.get("q", ""),
            "dates": dates,
            "start": dates["start"].isoformat() if dates["start"] else "",
            "end": dates["end"].isoformat() if dates["end"] else "",
            "options": options,
            "selected": {
                "owner": request.GET.get("owner", ""),
                "counterpart": request.GET.get("counterpart", ""),
                "currency": request.GET.get("currency", ""),
            },
            "person_label": "负责人",
            "counterpart_label": "客户",
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
    # 可见范围已放开到全公司，所以这里必须独立判断写权限。返回 403 而不是 404：
    # 记录确实存在、用户也看得到，只是不该由他改，说清楚比装作不存在好。
    if not can_edit_shipment(request.user, shipment):
        return forbidden_page(request, "这笔日报的客户不在你的负责范围内，只有该客户的业务员或管理员可以修改")
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
    if request.method != "POST":
        return JsonResponse({"error": "只允许使用 POST 请求"}, status=405)
    shipment = get_object_or_404(sales_queryset_for(request.user, request.company), pk=pk)
    # 服务层也会拒，但那是 PermissionError → 500。这里先转成能看懂的 403。
    if not can_edit_shipment(request.user, shipment):
        return forbidden_page(request, "这笔日报的客户不在你的负责范围内，只有该客户的业务员或管理员可以删除")
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
