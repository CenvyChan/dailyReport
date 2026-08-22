from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.responses import forbidden_page
from core.services.audit import record_audit
from core.services.permissions import is_administrator
from notifications.forms import MailingListForm
from notifications.mailer import send_daily_report
from notifications.models import DeliveryLog, MailingList


def _denied(request):
    if not is_administrator(request.user):
        return forbidden_page(request, "只有管理员可以维护邮件推送")
    if request.company is None:
        return forbidden_page(request, "请先选择公司")
    return None


def _snapshot(mailing_list):
    return {
        "company_id": mailing_list.company_id,
        "name": mailing_list.name,
        "scope": mailing_list.scope,
        "recipients": mailing_list.recipients,
        "cc_recipients": mailing_list.cc_recipients,
        "send_at": mailing_list.send_at.isoformat(),
        "attach_workbook": mailing_list.attach_workbook,
        "is_active": mailing_list.is_active,
    }


@login_required
def mailing_list_index(request):
    denied = _denied(request)
    if denied:
        return denied
    return render(
        request,
        "notifications/mailing_list.html",
        {
            "mailing_lists": MailingList.objects.filter(company=request.company),
            "logs": DeliveryLog.objects.filter(mailing_list__company=request.company).select_related("mailing_list")[:20],
        },
    )


@login_required
def mailing_list_create(request):
    denied = _denied(request)
    if denied:
        return denied
    form = MailingListForm(request.POST or None, company=request.company)
    if request.method == "POST" and form.is_valid():
        mailing_list = form.save()
        record_audit(actor=request.user, instance=mailing_list, action="CREATE", before={}, after=_snapshot(mailing_list))
        return redirect("notifications:mailing_list_index")
    return render(request, "notifications/mailing_list_form.html", {"form": form, "title": "新增收件组"})


@login_required
def mailing_list_edit(request, pk):
    denied = _denied(request)
    if denied:
        return denied
    mailing_list = get_object_or_404(MailingList, pk=pk, company=request.company)
    before = _snapshot(mailing_list)
    form = MailingListForm(request.POST or None, instance=mailing_list, company=request.company)
    if request.method == "POST" and form.is_valid():
        updated = form.save()
        record_audit(actor=request.user, instance=updated, action="UPDATE", before=before, after=_snapshot(updated))
        return redirect("notifications:mailing_list_index")
    return render(request, "notifications/mailing_list_form.html", {"form": form, "title": "编辑收件组"})


@login_required
def mailing_list_send_now(request, pk):
    """管理员手工补发/试发当天邮件，走与计划任务完全相同的发送路径。"""
    denied = _denied(request)
    if denied:
        return denied
    if request.method != "POST":
        return HttpResponseForbidden("只允许使用 POST 请求发送")
    mailing_list = get_object_or_404(MailingList, pk=pk, company=request.company)
    ok, detail = send_daily_report(mailing_list, timezone.localdate(), skip_when_empty=False)
    messages.add_message(request, messages.SUCCESS if ok else messages.ERROR, f"{mailing_list.name}：{detail}")
    return redirect("notifications:mailing_list_index")
