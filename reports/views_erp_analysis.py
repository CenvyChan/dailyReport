"""公司隔离的经营分析页面、后台任务入口和受保护下载。"""

from django import forms
from django.core import signing
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from urllib.parse import urlencode
from django.views.decorators.http import require_GET, require_POST

from core.responses import forbidden_page
from integrations.models import ErpAnalysisTask, KingdeeOrgBinding
from integrations.services.erp_analysis.catalog import REPORT_KINDS
from integrations.services.erp_analysis.common import period_window
from integrations.services.erp_analysis.public import SNAPSHOT_MAX_AGE, SNAPSHOT_SALT, bundle_name
from integrations.services.erp_analysis.runner import bundle_file, enqueue, render_report
from reports.erp_analysis_permissions import can_view_erp_analysis


class AnalysisForm(forms.Form):
    window_months = forms.TypedChoiceField(
        label="分析窗口",
        choices=[(1, "单月"), (3, "近3个月"), (12, "近12个月")],
        coerce=int,
        initial=12,
        required=False,
    )

    period = forms.DateField(
        label="分析月份", input_formats=["%Y-%m"], widget=forms.DateInput(format="%Y-%m", attrs={"type": "month"})
    )
    report_kinds = forms.MultipleChoiceField(
        label="分析内容",
        choices=[(key, value["name"]) for key, value in REPORT_KINDS.items()],
        widget=forms.CheckboxSelectMultiple,
    )

    def clean_period(self):
        period = self.cleaned_data["period"]
        if not 2000 <= period.year <= 2999 or period > timezone.localdate().replace(day=1):
            raise forms.ValidationError("请选择不晚于当前月份的有效分析月份")
        return period


def denied(request, *, api=False):
    if not request.company or not can_view_erp_analysis(request.user):
        return (
            JsonResponse({"error": "经营分析需要本公司管理员或报表查看权限"}, status=403)
            if api
            else forbidden_page(request, "经营分析包含全公司数据，需要管理员或报表查看权限")
        )
    return None


@login_required
@require_GET
def index(request):
    refusal = denied(request)
    if refusal:
        return refusal
    return page(request)


def page(request, form=None, status=200):
    previous_month = period_window(timezone.localdate().replace(day=1), 2)[0][0]
    binding = (
        KingdeeOrgBinding.objects.select_related("account")
        .filter(company=request.company, is_active=True, account__is_active=True)
        .first()
    )
    return render(
        request,
        "reports/erp_analysis.html",
        {
            "form": form
            or AnalysisForm(
                initial={"period": previous_month, "report_kinds": list(REPORT_KINDS), "window_months": 12}
            ),
            "catalog": REPORT_KINDS,
            "binding": binding,
            "tasks": ErpAnalysisTask.objects.filter(company=request.company).select_related("requested_by", "account")[
                :30
            ],
            "can_generate": can_view_erp_analysis(request.user),
            "last_month": previous_month,
        },
        status=status,
    )


@login_required
@require_POST
def generate(request):
    refusal = denied(request)
    if refusal:
        return refusal
    form = AnalysisForm(request.POST)
    if form.is_valid():
        try:
            task = enqueue(
                request.company,
                form.cleaned_data["period"],
                form.cleaned_data["report_kinds"],
                actor=request.user,
                window_months=form.cleaned_data.get("window_months") or 12,
            )
        except ValueError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "经营分析已加入队列，后台工作进程将依次生成。")
            return redirect("reports:erp_analysis_task", task_id=task.pk)
    return page(request, form, status=400)


def scoped_task(request, task_id):
    return get_object_or_404(
        ErpAnalysisTask.objects.select_related("company", "account", "requested_by"),
        pk=task_id,
        company=request.company,
    )


def task_items(task):
    return [
        {
            "kind": kind,
            "name": REPORT_KINDS.get(kind, {}).get("name", kind),
            "status": task.results.get(kind, {}).get("status", "PENDING"),
            "error": task.results.get(kind, {}).get("error", ""),
        }
        for kind in task.report_kinds
    ]


@login_required
@require_GET
def task_detail(request, task_id):
    refusal = denied(request)
    if refusal:
        return refusal
    task = scoped_task(request, task_id)
    return render(
        request,
        "reports/erp_analysis_task.html",
        {
            "task": task,
            "items": task_items(task),
            "finished": task.status not in (task.Status.PENDING, task.Status.RUNNING),
        },
    )


@login_required
@require_GET
def task_status(request, task_id):
    refusal = denied(request, api=True)
    if refusal:
        return refusal
    task = scoped_task(request, task_id)
    return JsonResponse(
        {
            "status": task.status,
            "label": task.get_status_display(),
            "items": task_items(task),
            "finished": task.status not in (task.Status.PENDING, task.Status.RUNNING),
        }
    )


@login_required
@require_GET
def report_view(request, task_id, kind):
    refusal = denied(request)
    if refusal:
        return refusal
    task = scoped_task(request, task_id)
    if kind not in REPORT_KINDS or task.results.get(kind, {}).get("status") != "SUCCESS":
        raise Http404("该分析尚未生成")
    response = HttpResponse(
        render_report(
            task,
            kind,
            download_url=reverse("reports:erp_analysis_download", args=[task.pk]) if task.bundle_path else None,
            contents_url=reverse("reports:erp_analysis_task", args=[task.pk]),
        )
    )
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_GET
def download(request, task_id):
    refusal = denied(request)
    if refusal:
        return refusal
    task = scoped_task(request, task_id)
    if task.status in (task.Status.PENDING, task.Status.RUNNING):
        raise Http404("分析仍在生成")
    try:
        file = bundle_file(task)
    except FileNotFoundError as exc:
        raise Http404(str(exc)) from exc
    response = FileResponse(
        file.open("rb"), as_attachment=True, filename=f"经营分析_{task.company.code}_{task.period:%Y-%m}_{task.pk}.zip"
    )
    response["Cache-Control"] = "private, no-store"
    return response


@require_GET
def public_snapshot(request, task_id, kind=None):
    token = request.GET.get("token", "")
    try:
        payload = signing.loads(token, salt=SNAPSHOT_SALT, max_age=SNAPSHOT_MAX_AGE)
    except signing.BadSignature:
        return HttpResponseForbidden("快照链接已失效，请联系管理员重新获取。")
    if not isinstance(payload, dict) or payload.get("task") != task_id:
        return HttpResponseForbidden("链接与分析任务不匹配。")
    task = get_object_or_404(
        ErpAnalysisTask.objects.select_related("company", "account"),
        pk=task_id,
        company_id=payload.get("company"),
        company__is_active=True,
    )
    if task.status in (task.Status.PENDING, task.Status.RUNNING):
        raise Http404("快照尚未生成")
    if request.GET.get("download") == "zip":
        try:
            file = bundle_file(task)
        except FileNotFoundError as exc:
            raise Http404(str(exc)) from exc
        response = FileResponse(file.open("rb"), as_attachment=True, filename=bundle_name(task))
    elif kind:
        if kind not in REPORT_KINDS or task.results.get(kind, {}).get("status") != "SUCCESS":
            raise Http404("该分析未生成")
        contents_url = reverse("reports:erp_analysis_public", args=[task.pk]) + "?" + urlencode({"token": token})
        response = HttpResponse(
            render_report(
                task,
                kind,
                download_url=contents_url + "&download=zip" if task.bundle_path else None,
                contents_url=contents_url,
            )
        )
    else:
        items = task_items(task)
        for item in items:
            item["description"] = REPORT_KINDS[item["kind"]]["description"]
        response = render(
            request,
            "reports/erp_analysis_public.html",
            {"task": task, "items": items, "token": token, "bundle_name": bundle_name(task)},
        )
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response
