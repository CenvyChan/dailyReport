from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.responses import forbidden_page
from core.services.audit import record_audit
from core.services.permissions import (
    can_view_comparison,
    editable_customer_ids,
    editable_supplier_ids,
    is_administrator,
)
from reports.exporters import workbook_response

from .models import (
    BusinessType,
    DingtalkApprovalInstance,
    KingdeePartyMapping,
    StockTransaction,
)
from .services.kingdee_compare import available_years, monthly_reconciliation

_BIZ_CHOICES = {BusinessType.SALES_OUT: "销售出库", BusinessType.PURCHASE_IN: "采购入库"}


def _view_denied(request):
    if not can_view_comparison(request.user, request.company):
        return forbidden_page(request, "集成数据核对需要管理员或报表查看权限")
    if request.company is None:
        return forbidden_page(request, "当前账号没有可进入的公司，请联系管理员授权")
    return None


def _requested_month(request, today):
    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
    except (TypeError, ValueError):
        return today.year, today.month
    if not 1 <= month <= 12 or not 2000 <= year <= 2999:
        return today.year, today.month
    return year, month


def _requested_biz(request):
    value = request.GET.get("biz")
    if value in _BIZ_CHOICES:
        return value
    return BusinessType.SALES_OUT


@login_required
def reconciliation_view(request):
    denied = _view_denied(request)
    if denied:
        return denied
    today = timezone.localdate()
    year, month = _requested_month(request, today)
    biz = _requested_biz(request)
    report = monthly_reconciliation(company=request.company, year=year, month=month, business_type=biz)
    years = available_years(request.company) or [today.year]
    return render(
        request,
        "integrations/reconciliation.html",
        {
            "report": report,
            "years": years,
            "months": range(1, 13),
            "biz": biz,
            "biz_label": _BIZ_CHOICES[biz],
            "biz_choices": _BIZ_CHOICES,
        },
    )


@login_required
def reconciliation_export(request):
    denied = _view_denied(request)
    if denied:
        return denied
    today = timezone.localdate()
    year, month = _requested_month(request, today)
    biz = _requested_biz(request)
    report = monthly_reconciliation(company=request.company, year=year, month=month, business_type=biz)
    headers = ["日期", "系统笔数", "系统数量", "系统金额", "金蝶单据数", "金蝶数量", "金蝶金额", "金额差", "数量差"]
    rows = [
        [
            r["date"], r["sys_count"], r["sys_qty"], r["sys_amount"],
            r["k3_count"], r["k3_qty"], r["k3_amount"], r["amount_diff"], r["qty_diff"],
        ]
        for r in report["rows"]
    ]
    content = workbook_response(headers, rows)
    response = HttpResponse(
        content, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = (
        f'attachment; filename="reconciliation-{request.company.code}-{biz}-{year}{month:02d}.xlsx"'
    )
    return response


@login_required
def stock_list_view(request):
    denied = _view_denied(request)
    if denied:
        return denied
    biz = _requested_biz(request)
    qs = StockTransaction.objects.filter(company=request.company, business_type=biz, is_active=True)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(bill_no__icontains=q) | Q(k3_party_name__icontains=q) | Q(fid__icontains=q))
    qs = qs.order_by("-biz_date", "-id")
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(
        request,
        "integrations/stock_list.html",
        {"page": page, "biz": biz, "biz_label": _BIZ_CHOICES[biz], "biz_choices": _BIZ_CHOICES, "q": q},
    )


@login_required
def stock_detail_view(request, pk):
    denied = _view_denied(request)
    if denied:
        return denied
    txn = get_object_or_404(StockTransaction, pk=pk, company=request.company)
    return render(request, "integrations/stock_detail.html", {"txn": txn, "lines": txn.lines.all()})


@login_required
def approval_list_view(request):
    denied = _view_denied(request)
    if denied:
        return denied
    qs = DingtalkApprovalInstance.objects.filter(company=request.company)
    status = request.GET.get("status", "").strip()
    if status:
        qs = qs.filter(status=status)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(originator_name__icontains=q) | Q(process_instance_id__icontains=q))
    qs = qs.order_by("-create_time", "-id")
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(request, "integrations/approval_list.html", {"page": page, "status": status, "q": q})


def _visible_to(mapping, cust_ids, sup_ids):
    """业务员可见性：已挂接的看归属人是否是自己，未挂接的看候选里有没有自己负责的客商。"""
    if mapping.party_type == KingdeePartyMapping.PartyType.CUSTOMER:
        ids, linked = cust_ids, mapping.customer_id
    else:
        ids, linked = sup_ids, mapping.supplier_id
    if linked is not None:
        return linked in ids
    return any(c.get("id") in ids for c in (mapping.candidates or []))


def _party_mapping_save(request, admin, cust_ids, sup_ids):
    """逐条保存人工挂接：按归属校验，越权/冲突一律明确报错，不静默覆盖。"""
    from core.models import Customer, Supplier

    mapping = get_object_or_404(KingdeePartyMapping, pk=request.POST.get("mapping_id"), company=request.company)
    choice = (request.POST.get("choice") or "").strip()
    return_status = request.POST.get("return_status", "PENDING")
    redirect_to = f"{request.path}?status={return_status}"
    is_customer = mapping.party_type == KingdeePartyMapping.PartyType.CUSTOMER
    owned = (cust_ids if is_customer else sup_ids) or set()

    def deny(msg):
        messages.error(request, msg)
        return redirect(redirect_to)

    # 业务员不能改动当前挂到「非自己负责客商」的映射：保护他人认领结果，不静默覆盖。
    current_id = mapping.customer_id if is_customer else mapping.supplier_id
    if not admin and current_id is not None and current_id not in owned:
        return deny("该映射当前挂接的客商不在你的负责范围内，不能修改")

    before = {"status": mapping.match_status, "customer": mapping.customer_id, "supplier": mapping.supplier_id}
    if choice:
        if not choice.isdigit():
            return deny("选择无效，未保存")
        cid = int(choice)
        if admin:
            model = Customer if is_customer else Supplier
            if not model.objects.filter(pk=cid, company=request.company).exists():
                return deny("所选主数据不属于当前公司，未保存")
        elif cid not in owned:
            return deny("所选客商不在你的负责范围内，只能挂接你负责的客商")
        mapping.customer = None
        mapping.supplier = None
        if is_customer:
            mapping.customer_id = cid
        else:
            mapping.supplier_id = cid
        mapping.match_status = KingdeePartyMapping.MatchStatus.MANUAL
    else:
        if not admin:
            return deny("清除挂接仅管理员可操作")
        mapping.customer = None
        mapping.supplier = None
        mapping.match_status = KingdeePartyMapping.MatchStatus.UNMATCHED

    mapping.save()
    after = {"status": mapping.match_status, "customer": mapping.customer_id, "supplier": mapping.supplier_id}
    record_audit(actor=request.user, instance=mapping, action="UPDATE", before=before, after=after)
    messages.success(request, f"已更新映射：{mapping.k3_name}")
    return redirect(redirect_to)


@login_required
def party_mapping_view(request):
    denied = _view_denied(request)
    if denied:
        return denied

    admin = is_administrator(request.user)
    cust_ids = None if admin else editable_customer_ids(request.user, request.company)
    sup_ids = None if admin else editable_supplier_ids(request.user, request.company)

    if request.method == "POST":
        return _party_mapping_save(request, admin, cust_ids, sup_ids)

    status = request.GET.get("status", "PENDING")
    base = KingdeePartyMapping.objects.filter(company=request.company).select_related("customer", "supplier")
    if status != "ALL":
        base = base.filter(match_status=status)

    if admin:
        rows = list(base.order_by("party_type", "k3_name"))
    else:
        ptypes = []
        if cust_ids:
            ptypes.append(KingdeePartyMapping.PartyType.CUSTOMER)
        if sup_ids:
            ptypes.append(KingdeePartyMapping.PartyType.SUPPLIER)
        scoped = base.filter(party_type__in=ptypes).order_by("party_type", "k3_name") if ptypes else base.none()
        rows = [m for m in scoped if _visible_to(m, cust_ids, sup_ids)]

    page = Paginator(rows, 50).get_page(request.GET.get("page"))
    for m in page.object_list:
        owned_ids = None if admin else (cust_ids if m.party_type == KingdeePartyMapping.PartyType.CUSTOMER else sup_ids)
        m.view_candidates = [
            dict(c, owned=(owned_ids is None or c.get("id") in owned_ids)) for c in (m.candidates or [])
        ]
    return render(
        request,
        "integrations/party_mapping.html",
        {
            "page": page,
            "status": status,
            "status_choices": KingdeePartyMapping.MatchStatus.choices,
            "is_admin": admin,
        },
    )
