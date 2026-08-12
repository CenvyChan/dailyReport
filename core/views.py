from io import BytesIO

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from core.forms import ExchangeRateForm, UserCreateForm, UserPasswordResetForm
from core.importers import (
    commit_customer_import,
    commit_supplier_import,
    commit_user_import,
    preview_customer_import,
    preview_supplier_import,
    preview_user_import,
)
from core.models import ExchangeRate
from core.services.master_data import save_exchange_rate
from core.services.permissions import is_administrator
from core.services.users import create_user_account, reset_user_password, role_label


def _admin_only(request):
    return is_administrator(request.user)


@login_required
def rate_list(request):
    if not _admin_only(request):
        return HttpResponseForbidden("只有管理员可以维护汇率")
    return render(request, "core/exchange_rate_list.html", {"rates": ExchangeRate.objects.all()})


@login_required
def rate_create(request):
    if not _admin_only(request):
        return HttpResponseForbidden("只有管理员可以维护汇率")
    form = ExchangeRateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        save_exchange_rate(actor=request.user, data=form.cleaned_data)
        return redirect("core:rate_list")
    return render(request, "core/exchange_rate_form.html", {"form": form, "title": "新增汇率"})


@login_required
def rate_edit(request, pk):
    if not _admin_only(request):
        return HttpResponseForbidden("只有管理员可以维护汇率")
    rate = get_object_or_404(ExchangeRate, pk=pk)
    form = ExchangeRateForm(request.POST or None, instance=rate)
    if request.method == "POST" and form.is_valid():
        save_exchange_rate(actor=request.user, instance=rate, data=form.cleaned_data)
        return redirect("core:rate_list")
    return render(request, "core/exchange_rate_form.html", {"form": form, "title": "编辑汇率"})


@login_required
def user_list(request):
    if not _admin_only(request):
        return HttpResponseForbidden("只有管理员可以管理用户")
    users = User.objects.prefetch_related("groups").order_by("username")
    user_rows = [
        {"user": user, "roles": [role_label(group.name) for group in user.groups.all()]}
        for user in users
    ]
    return render(request, "core/user_list.html", {"user_rows": user_rows})


@login_required
def user_create(request):
    if not _admin_only(request):
        return HttpResponseForbidden("只有管理员可以管理用户")
    form = UserCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        create_user_account(actor=request.user, data=form.cleaned_data)
        return redirect("core:user_list")
    return render(request, "core/user_form.html", {"form": form, "title": "新增用户"})


@login_required
def user_password_reset(request, pk):
    if not _admin_only(request):
        return HttpResponseForbidden("只有管理员可以管理用户")
    target = get_object_or_404(User, pk=pk)
    form = UserPasswordResetForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        reset_user_password(actor=request.user, user=target, password=form.cleaned_data["password"])
        return redirect("core:user_list")
    return render(request, "core/user_form.html", {"form": form, "title": f"重置 {target.username} 的密码"})


def _import_page(request, *, title, preview_url, commit_url, instructions):
    if not _admin_only(request):
        return HttpResponseForbidden("只有管理员可以导入")
    return render(
        request,
        "imports/import_page.html",
        {
            "title": title,
            "preview_url": preview_url,
            "commit_url": commit_url,
            "instructions": instructions,
        },
    )


def _preview(request, previewer):
    if not _admin_only(request):
        return HttpResponseForbidden("只有管理员可以导入")
    uploaded = request.FILES.get("file")
    if uploaded is None:
        return JsonResponse({"error": "请上传文件"}, status=400)
    preview = previewer(BytesIO(uploaded.read()))
    return JsonResponse({"valid_row_count": preview.valid_row_count, "error_rows": preview.error_rows})


def _commit(request, previewer, committer):
    if not _admin_only(request):
        return HttpResponseForbidden("只有管理员可以导入")
    uploaded = request.FILES.get("file")
    if uploaded is None:
        return JsonResponse({"error": "请上传文件"}, status=400)
    preview = previewer(BytesIO(uploaded.read()))
    if preview.error_rows:
        return JsonResponse({"valid_row_count": preview.valid_row_count, "error_rows": preview.error_rows}, status=400)
    return JsonResponse({"imported": committer(preview, actor=request.user)})


@login_required
def customer_import_page(request):
    return _import_page(
        request,
        title="客户导入",
        preview_url="core:customer_import_preview",
        commit_url="core:customer_import_commit",
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
def supplier_import_page(request):
    return _import_page(
        request,
        title="供应商导入",
        preview_url="core:supplier_import_preview",
        commit_url="core:supplier_import_commit",
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
def user_import_page(request):
    return _import_page(
        request,
        title="用户导入",
        preview_url="core:user_import_preview",
        commit_url="core:user_import_commit",
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
