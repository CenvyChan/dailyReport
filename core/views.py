from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import Http404, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from core.forms import (
    CustomerForm,
    ExchangeRateForm,
    SupplierForm,
    UserCreateForm,
    UserPasswordResetForm,
)
from core.importers import (
    commit_customer_import,
    commit_supplier_import,
    commit_user_import,
    preview_customer_import,
    preview_supplier_import,
    preview_user_import,
)
from core.models import Customer, ExchangeRate, Supplier
from core.responses import forbidden_page
from core.services.listing import paginate, search_queryset
from core.services.master_data import save_customer, save_exchange_rate, save_supplier
from core.services.permissions import (
    can_access_purchase,
    can_access_sales,
    can_edit_customer,
    can_edit_supplier,
    editable_customer_ids,
    editable_supplier_ids,
    is_administrator,
)
from core.services.users import (
    can_toggle_active,
    create_user_account,
    reset_user_password,
    role_label,
    set_user_active,
)
from core.templates_export import TEMPLATES, build_template
from core.excel import read_rows
from core.uploads import error_workbook_response, import_response, read_upload


def _admin_only(request):
    return is_administrator(request.user)


def _admin_company_denied(request, *, as_page=True):
    """基础资料按公司隔离，所以管理员也必须先有一个当前公司。

    as_page=False 用于 fetch 调用的导入接口：前端要读 body，给它 HTML 会解析失败。
    """
    reject = (lambda message: forbidden_page(request, message)) if as_page else HttpResponseForbidden
    if not _admin_only(request):
        return reject("只有管理员可以维护基础资料")
    if request.company is None:
        return reject("请先选择公司")
    return None


@login_required
def rate_list(request):
    denied = _admin_company_denied(request)
    if denied:
        return denied
    page, querystring = paginate(request, ExchangeRate.objects.filter(company=request.company))
    return render(
        request,
        "core/exchange_rate_list.html",
        {"rates": page.object_list, "page": page, "querystring": querystring},
    )


@login_required
def rate_create(request):
    denied = _admin_company_denied(request)
    if denied:
        return denied
    form = ExchangeRateForm(request.POST or None, company=request.company)
    if request.method == "POST" and form.is_valid():
        save_exchange_rate(actor=request.user, company=request.company, data=form.cleaned_data)
        return redirect("core:rate_list")
    return render(request, "core/exchange_rate_form.html", {"form": form, "title": "新增汇率"})


@login_required
def rate_edit(request, pk):
    denied = _admin_company_denied(request)
    if denied:
        return denied
    rate = get_object_or_404(ExchangeRate, pk=pk, company=request.company)
    form = ExchangeRateForm(request.POST or None, instance=rate, company=request.company)
    if request.method == "POST" and form.is_valid():
        save_exchange_rate(actor=request.user, company=request.company, instance=rate, data=form.cleaned_data)
        return redirect("core:rate_list")
    return render(request, "core/exchange_rate_form.html", {"form": form, "title": "编辑汇率"})


@login_required
def user_list(request):
    if not _admin_only(request):
        return forbidden_page(request, "只有管理员可以管理用户")
    users = User.objects.prefetch_related("groups", "companymembership_set__company").order_by("username")
    user_rows = [
        {
            "user": user,
            "roles": [role_label(group.name) for group in user.groups.all()],
            "companies": [membership.company.name for membership in user.companymembership_set.all()],
            # 不能停用的账号干脆不显示按钮，别让人点了才看到报错。
            "can_toggle": can_toggle_active(actor=request.user, user=user),
        }
        for user in users
    ]
    return render(request, "core/user_list.html", {"user_rows": user_rows})


@login_required
def user_create(request):
    if not _admin_only(request):
        return forbidden_page(request, "只有管理员可以管理用户")
    form = UserCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        create_user_account(actor=request.user, data=form.cleaned_data)
        return redirect("core:user_list")
    return render(request, "core/user_form.html", {"form": form, "title": "新增用户"})


@login_required
def user_password_reset(request, pk):
    if not _admin_only(request):
        return forbidden_page(request, "只有管理员可以管理用户")
    target = get_object_or_404(User, pk=pk)
    form = UserPasswordResetForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        reset_user_password(actor=request.user, user=target, password=form.cleaned_data["password"])
        return redirect("core:user_list")
    return render(request, "core/user_form.html", {"form": form, "title": f"重置 {target.username} 的密码"})


@login_required
def user_set_active(request, pk):
    """停用/启用账号。员工离职是日常动作，不该逼管理员去 Django admin 改 is_active。"""
    if not _admin_only(request):
        return forbidden_page(request, "只有管理员可以管理用户")
    if request.method != "POST":
        return HttpResponseForbidden("只允许使用 POST 请求")
    target = get_object_or_404(User, pk=pk)
    activate = request.POST.get("is_active") == "1"
    try:
        set_user_active(actor=request.user, user=target, is_active=activate)
    except PermissionError as error:
        messages.error(request, str(error))
    else:
        messages.success(
            request, f"已{'启用' if activate else '停用'}账号「{target.username}」"
        )
    return redirect("core:user_list")


def user_guide(request):
    """直接把 docs/guide 下的指南发出来，避免复制一份到 static 造成两边不同步。
    登录页也要能打开，所以不加 login_required。"""
    path = settings.BASE_DIR / "docs" / "guide" / "用户使用指南.html"
    if not path.exists():
        raise Http404("使用指南文件不存在")
    return HttpResponse(path.read_text(encoding="utf-8"), content_type="text/html; charset=utf-8")


@login_required
def import_template_download(request, kind):
    if not _admin_only(request):
        return forbidden_page(request, "只有管理员可以下载导入模板")
    if kind not in TEMPLATES:
        raise Http404("没有这个导入模板")
    filename, content = build_template(kind)
    response = HttpResponse(
        content, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(filename)}"
    return response


def _import_page(request, *, title, preview_url, commit_url, instructions, template_kind=None, errors_url=None):
    denied = _admin_company_denied(request)
    if denied:
        return denied
    return render(
        request,
        "imports/import_page.html",
        {
            "title": title,
            "preview_url": preview_url,
            "commit_url": commit_url,
            "errors_url": errors_url,
            "instructions": [f"数据将导入当前公司「{request.company.name}」。", *instructions],
            "template_kind": template_kind,
        },
    )


def _preview(request, previewer):
    denied = _admin_company_denied(request, as_page=False)
    if denied:
        return denied

    def handler():
        content, _ = read_upload(request)
        preview = previewer(content)
        return JsonResponse(
            {"valid_row_count": preview.valid_row_count, "error_rows": preview.error_rows}
        )

    return import_response(handler)


def _errors_export(request, previewer, *, filename):
    """把校验错误连同原始行导出成 Excel。

    重新解析一遍上传的文件而不是缓存预览结果：会话里存几千行原始数据代价大，
    而导出是低频操作，多解析一次可以接受。
    """
    denied = _admin_company_denied(request, as_page=False)
    if denied:
        return denied

    def handler():
        content, _ = read_upload(request)
        preview = previewer(content)
        content.seek(0)
        rows = read_rows(content)
        return error_workbook_response([("错误清单", rows, preview.error_rows)], filename=filename)

    return import_response(handler)


def _commit(request, previewer, committer):
    denied = _admin_company_denied(request, as_page=False)
    if denied:
        return denied

    def handler():
        content, _ = read_upload(request)
        preview = previewer(content)
        if preview.error_rows:
            return JsonResponse(
                {"valid_row_count": preview.valid_row_count, "error_rows": preview.error_rows},
                status=400,
            )
        return JsonResponse(
            {"imported": committer(preview, actor=request.user, company=request.company)}
        )

    return import_response(handler)


@login_required
def customer_import_page(request):
    return _import_page(
        request,
        title="客户导入",
        preview_url="core:customer_import_preview",
        commit_url="core:customer_import_commit",
        errors_url="core:customer_import_errors",
        template_kind="customer",
        instructions=[
            "Excel 首行使用“客户名称”列，也兼容“名称”列。",
            "选择文件后先预览，确认没有错误再点击正式导入。",
            "同名客户不会重复创建；已停用的同名客户会重新启用。",
        ],
    )


@login_required
def customer_import_preview(request):
    return _preview(request, preview_customer_import)


@login_required
def customer_import_commit(request):
    return _commit(request, preview_customer_import, commit_customer_import)


@login_required
def customer_import_errors(request):
    return _errors_export(request, preview_customer_import, filename="客户导入错误清单.xlsx")


@login_required
def supplier_import_page(request):
    return _import_page(
        request,
        title="供应商导入",
        preview_url="core:supplier_import_preview",
        commit_url="core:supplier_import_commit",
        errors_url="core:supplier_import_errors",
        template_kind="supplier",
        instructions=[
            "Excel 首行使用“供应商名称”列，也兼容“供应商”或“名称”列。",
            "选择文件后先预览，确认没有错误再点击正式导入。",
            "同名供应商不会重复创建；已停用的同名供应商会重新启用。",
        ],
    )


@login_required
def supplier_import_preview(request):
    return _preview(request, preview_supplier_import)


@login_required
def supplier_import_commit(request):
    return _commit(request, preview_supplier_import, commit_supplier_import)


@login_required
def supplier_import_errors(request):
    return _errors_export(request, preview_supplier_import, filename="供应商导入错误清单.xlsx")


@login_required
def user_import_page(request):
    return _import_page(
        request,
        title="用户导入",
        preview_url="core:user_import_preview",
        commit_url="core:user_import_commit",
        errors_url="core:user_import_errors",
        template_kind="user",
        instructions=[
            "Excel 首行字段为：用户名、姓名、角色、初始密码。",
            "角色可填写：管理员、销售、采购、报表查看者。",
            "选择文件后先预览；已有用户名不会覆盖，错误行需要先修正。",
            "导入完成后，用户首次登录后必须自行修改密码。",
        ],
    )


@login_required
def user_import_preview(request):
    return _preview(request, preview_user_import)


@login_required
def user_import_commit(request):
    return _commit(request, preview_user_import, commit_user_import)


@login_required
def user_import_errors(request):
    return _errors_export(request, preview_user_import, filename="用户导入错误清单.xlsx")


def _master_denied(request, allowed, denial):
    """客户/供应商维护：销售管客户、采购管供应商，管理员两者皆可。"""
    if not allowed(request.user):
        return forbidden_page(request, denial)
    if request.company is None:
        return forbidden_page(request, "当前账号没有可进入的公司，请联系管理员授权")
    return None


def _master_list(
    request, *, model, title, search_fields, create_url, edit_url, import_url, unit, editable_ids
):
    """主数据列表。业务员只看到自己负责的那些——绑定关系决定谁维护这条资料。

    此前起点是 model.objects.filter(company=...)，任何 sales 组成员能看到并
    编辑本公司全部客户，和「新增日报时只能选到自己绑定的客户」自相矛盾。
    """
    queryset = model.objects.filter(company=request.company)
    editable = editable_ids(request.user, request.company)
    if editable is not None:
        queryset = queryset.filter(pk__in=editable)
    queryset = search_queryset(queryset, request.GET.get("q"), search_fields)
    if request.GET.get("status") == "active":
        queryset = queryset.filter(is_active=True)
    elif request.GET.get("status") == "inactive":
        queryset = queryset.filter(is_active=False)
    page, querystring = paginate(request, queryset.order_by("name"))
    return render(
        request,
        "core/master_list.html",
        {
            "title": title,
            "page": page,
            "rows": page.object_list,
            "querystring": querystring,
            "search": request.GET.get("q", ""),
            "status": request.GET.get("status", ""),
            "create_url": create_url,
            "edit_url": edit_url,
            "import_url": import_url,
            "unit": unit,
            "can_import": is_administrator(request.user),
        },
    )


@login_required
def customer_list(request):
    denied = _master_denied(request, can_access_sales, "只有销售或管理员可以查看客户")
    if denied:
        return denied
    return _master_list(
        request, model=Customer, title="客户维护", search_fields=("name",),
        create_url="core:customer_create", edit_url="core:customer_edit",
        import_url="core:customer_import_page", unit="客户",
        editable_ids=editable_customer_ids,
    )


@login_required
def customer_create(request):
    denied = _master_denied(request, can_access_sales, "只有销售或管理员可以维护客户")
    if denied:
        return denied
    # actor 传给表单：业务员自己新建时默认把自己勾为负责人，否则建完就看不见
    form = CustomerForm(request.POST or None, company=request.company, actor=request.user)
    if request.method == "POST" and form.is_valid():
        save_customer(actor=request.user, company=request.company, data=form.cleaned_data)
        return redirect("core:customer_list")
    return render(request, "core/master_form.html", {"form": form, "title": "新增客户", "back_url": "core:customer_list"})


@login_required
def customer_edit(request, pk):
    denied = _master_denied(request, can_access_sales, "只有销售或管理员可以维护客户")
    if denied:
        return denied
    customer = get_object_or_404(Customer, pk=pk, company=request.company)
    # 列表已按绑定过滤，但直接输 URL 仍进得来，所以这里独立判断
    if not can_edit_customer(request.user, customer):
        return forbidden_page(request, "这个客户不在你的负责范围内，只有负责它的业务员或管理员可以维护")
    form = CustomerForm(request.POST or None, instance=customer, company=request.company, actor=request.user)
    if request.method == "POST" and form.is_valid():
        save_customer(actor=request.user, company=request.company, data=form.cleaned_data, instance=customer)
        return redirect("core:customer_list")
    return render(request, "core/master_form.html", {"form": form, "title": "编辑客户", "back_url": "core:customer_list"})


@login_required
def supplier_list(request):
    denied = _master_denied(request, can_access_purchase, "只有采购或管理员可以查看供应商")
    if denied:
        return denied
    return _master_list(
        request, model=Supplier, title="供应商维护", search_fields=("name",),
        create_url="core:supplier_create", edit_url="core:supplier_edit",
        import_url="core:supplier_import_page", unit="供应商",
        editable_ids=editable_supplier_ids,
    )


@login_required
def supplier_create(request):
    denied = _master_denied(request, can_access_purchase, "只有采购或管理员可以维护供应商")
    if denied:
        return denied
    form = SupplierForm(request.POST or None, company=request.company, actor=request.user)
    if request.method == "POST" and form.is_valid():
        save_supplier(actor=request.user, company=request.company, data=form.cleaned_data)
        return redirect("core:supplier_list")
    return render(request, "core/master_form.html", {"form": form, "title": "新增供应商", "back_url": "core:supplier_list"})


@login_required
def supplier_edit(request, pk):
    denied = _master_denied(request, can_access_purchase, "只有采购或管理员可以维护供应商")
    if denied:
        return denied
    supplier = get_object_or_404(Supplier, pk=pk, company=request.company)
    if not can_edit_supplier(request.user, supplier):
        return forbidden_page(request, "这个供应商不在你的负责范围内，只有负责它的采购员或管理员可以维护")
    form = SupplierForm(request.POST or None, instance=supplier, company=request.company, actor=request.user)
    if request.method == "POST" and form.is_valid():
        save_supplier(actor=request.user, company=request.company, data=form.cleaned_data, instance=supplier)
        return redirect("core:supplier_list")
    return render(request, "core/master_form.html", {"form": form, "title": "编辑供应商", "back_url": "core:supplier_list"})
