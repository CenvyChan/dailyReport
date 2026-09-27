"""金蝶库存发生（销售出库/采购入库）同步：拉数 → 按 FID 幂等 upsert → 失效对账 → 客商映射。

窗口默认当前月份且 FDate < 今天；重拉窗口做幂等 upsert，窗口内金蝶已删/反审核的
单据（FID 不再出现）置为 is_active=False（软删）。
"""

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from core.models import Company, Customer, Supplier
from integrations.models import (
    BusinessType,
    KingdeeFormConfig,
    KingdeeOrgBinding,
    KingdeePartyMapping,
    StockTransaction,
    StockTransactionLine,
    SyncRun,
)
from integrations.services import kingdee_client
from integrations.services.party_match import decide

logger = logging.getLogger("integrations")

HEADER_ROLES = ("fid", "bill_no", "date", "status", "approve_date", "org_number", "party_number", "party_name", "currency")
LINE_ROLES = ("entry_id", "material_number", "material_name", "qty", "unit", "price", "amount")


def _dec(value):
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _parse_date(value):
    if not value:
        return None
    text = str(value).replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:19] if " " in text else text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_dt(value):
    if not value:
        return None
    text = str(value).replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
        try:
            naive = datetime.strptime(text[:19] if " " in text else text, fmt)
            return timezone.make_aware(naive) if timezone.is_naive(naive) else naive
        except ValueError:
            continue
    return None


def _window(form, as_of, window_override=None):
    """返回 (window_start, window_end)。窗口内条件为 date_field >= start AND < end。

    window_override 显式指定 (start, end) 时优先用它（手动补历史月用）。
    """
    if window_override:
        return window_override
    if form.window_mode == KingdeeFormConfig.WindowMode.TRAILING_DAYS:
        from datetime import timedelta

        return as_of - timedelta(days=form.trailing_days or 7), as_of
    return as_of.replace(day=1), as_of  # 当前月份


class _PartyResolver:
    """按公司缓存系统客商简称列表，惰性创建/更新映射；不覆盖人工确定(MANUAL)的结果。"""

    def __init__(self, company):
        self.company = company
        self._locals = {}
        self._cache = {}

    def _local_names(self, party_type):
        if party_type not in self._locals:
            if party_type == KingdeePartyMapping.PartyType.CUSTOMER:
                qs = Customer.objects.filter(company=self.company, is_active=True).values_list("id", "name")
            else:
                qs = Supplier.objects.filter(company=self.company, is_active=True).values_list("id", "name")
            self._locals[party_type] = list(qs)
        return self._locals[party_type]

    def resolve(self, business_type, k3_number, k3_name):
        if not k3_number and not k3_name:
            return None
        party_type = (
            KingdeePartyMapping.PartyType.CUSTOMER
            if business_type == BusinessType.SALES_OUT
            else KingdeePartyMapping.PartyType.SUPPLIER
        )
        key = (party_type, k3_number or k3_name)
        if key in self._cache:
            return self._cache[key]
        mapping, created = KingdeePartyMapping.objects.get_or_create(
            company=self.company,
            party_type=party_type,
            k3_number=k3_number or k3_name,
            defaults={"k3_name": k3_name},
        )
        # 人工确定的不再自动改动。
        if mapping.match_status != KingdeePartyMapping.MatchStatus.MANUAL:
            if mapping.k3_name != k3_name and k3_name:
                mapping.k3_name = k3_name
            status, resolved_id, candidates = decide(k3_name or k3_number, self._local_names(party_type))
            mapping.match_status = status
            mapping.candidates = candidates
            mapping.customer = None
            mapping.supplier = None
            if status == "AUTO" and resolved_id:
                if party_type == KingdeePartyMapping.PartyType.CUSTOMER:
                    mapping.customer_id = resolved_id
                else:
                    mapping.supplier_id = resolved_id
            mapping.save()
        self._cache[key] = mapping
        return mapping


def _build_filter(form, binding, window_start, window_end):
    fmap = form.field_map()
    date_field = fmap.get("date", "FDate")
    parts = [f"{date_field} >= '{window_start:%Y-%m-%d}'", f"{date_field} < '{window_end:%Y-%m-%d}'"]
    if form.status_filter:
        status_field = fmap.get("status", "FDocumentStatus")
        parts.append(f"{status_field} = '{form.status_filter}'")
    org_field = fmap.get("org_number")
    if org_field and binding.org_number:
        parts.append(f"{org_field} = '{binding.org_number}'")
    return " AND ".join(parts)


def _group_rows(rows, roles):
    """按 fid 分组：{fid: {"header": {...}, "lines": [ {...} ]}}。"""
    grouped = {}
    fid_idx = roles.index("fid") if "fid" in roles else 0
    for row in rows:
        record = {role: (row[i] if i < len(row) else None) for i, role in enumerate(roles)}
        fid = str(record.get("fid") or "").strip()
        if not fid:
            continue
        bucket = grouped.setdefault(fid, {"header": record, "lines": []})
        bucket["lines"].append(record)
    return grouped


def _sync_binding_form(binding, form, run, sdk, resolver, as_of, dry_run, window_override=None):
    company = binding.company
    window_start, window_end = _window(form, as_of, window_override)
    fmap = form.field_map()
    roles = list(fmap.keys())
    field_keys = ",".join(fmap[r] for r in roles)
    filter_string = _build_filter(form, binding, window_start, window_end)
    order = fmap.get("fid", "FID")

    rows = kingdee_client.query_bill(
        sdk, form_id=form.form_id, field_keys=field_keys, filter_string=filter_string, order_string=order
    )
    grouped = _group_rows(rows, roles)
    if dry_run:
        return len(grouped), 0

    upserted = 0
    now = timezone.now()
    with transaction.atomic():
        for fid, group in grouped.items():
            header = group["header"]
            biz_date = _parse_date(header.get("date"))
            if biz_date is None:
                continue
            line_records = group["lines"]
            total_amount = sum((_dec(ln.get("amount")) for ln in line_records), Decimal("0"))
            total_quantity = sum((_dec(ln.get("qty")) for ln in line_records), Decimal("0"))
            k3_party_number = str(header.get("party_number") or "")
            k3_party_name = str(header.get("party_name") or "")
            mapping = resolver.resolve(form.business_type, k3_party_number, k3_party_name) if (k3_party_number or k3_party_name) else None
            txn, _ = StockTransaction.objects.update_or_create(
                company=company,
                form_id=form.form_id,
                fid=fid,
                defaults={
                    "business_type": form.business_type,
                    "bill_no": str(header.get("bill_no") or ""),
                    "biz_date": biz_date,
                    "doc_status": str(header.get("status") or ""),
                    "approve_date": _parse_dt(header.get("approve_date")),
                    "org_number": str(header.get("org_number") or binding.org_number or ""),
                    "k3_party_number": k3_party_number,
                    "k3_party_name": k3_party_name,
                    "party": mapping,
                    "currency": str(header.get("currency") or ""),
                    "total_amount": total_amount,
                    "total_quantity": total_quantity,
                    "is_active": True,
                    "disabled_at": None,
                    "sync_run": run,
                },
            )
            txn.lines.all().delete()
            lines = []
            for i, ln in enumerate(line_records, start=1):
                entry_id = str(ln.get("entry_id") or "").strip() or f"{fid}-{i}"
                lines.append(
                    StockTransactionLine(
                        transaction=txn,
                        entry_id=entry_id,
                        seq=i,
                        material_number=str(ln.get("material_number") or ""),
                        material_name=str(ln.get("material_name") or ""),
                        quantity=_dec(ln.get("qty")),
                        unit=str(ln.get("unit") or ""),
                        unit_price=_dec(ln.get("price")),
                        amount=_dec(ln.get("amount")),
                    )
                )
            StockTransactionLine.objects.bulk_create(lines)
            upserted += 1

        # 失效对账：窗口内、本次未见到的 FID → 软删。
        stale = (
            StockTransaction.objects.filter(
                company=company,
                form_id=form.form_id,
                biz_date__gte=window_start,
                biz_date__lt=window_end,
                is_active=True,
            )
            .exclude(fid__in=list(grouped.keys()))
        )
        disabled = stale.update(is_active=False, disabled_at=now)
    return upserted, disabled


def sync_kingdee(as_of=None, company=None, dry_run=False, window_override=None):
    """对每个启用的公司-组织绑定，同步所有启用的表单配置。返回逐公司结果列表。

    window_override=(start, end)：显式窗口，用于手动补拉指定历史月（覆盖 form 的窗口模式）。
    """
    as_of = as_of or timezone.localdate()
    run_window_start = window_override[0] if window_override else as_of.replace(day=1)
    run_window_end = window_override[1] if window_override else as_of
    bindings = KingdeeOrgBinding.objects.filter(
        is_active=True, account__is_active=True
    ).select_related("account", "company")
    if company is not None:
        bindings = bindings.filter(company=company)
    forms = list(KingdeeFormConfig.objects.filter(is_active=True))
    results = []

    for binding in bindings:
        run = None
        if not dry_run:
            run = SyncRun.objects.create(
                integration=SyncRun.Integration.KINGDEE,
                company=binding.company,
                window_start=run_window_start,
                window_end=run_window_end,
                status=SyncRun.Status.RUNNING,
            )
        try:
            sdk = kingdee_client.build_sdk(binding.account)
            resolver = _PartyResolver(binding.company)
            total_up = total_dis = 0
            for form in forms:
                up, dis = _sync_binding_form(binding, form, run, sdk, resolver, as_of, dry_run, window_override)
                total_up += up
                total_dis += dis
            if run is not None:
                run.status = SyncRun.Status.SUCCESS
                run.rows_upserted = total_up
                run.rows_disabled = total_dis
                run.finished_at = timezone.now()
                run.save(update_fields=["status", "rows_upserted", "rows_disabled", "finished_at"])
            results.append({"company": binding.company, "upserted": total_up, "disabled": total_dis, "error": None})
        except Exception as exc:  # noqa: BLE001 - 单公司失败不应中断其他公司
            logger.exception("金蝶同步失败 company=%s", binding.company)
            if run is not None:
                run.status = SyncRun.Status.FAILED
                run.message = str(exc)
                run.finished_at = timezone.now()
                run.save(update_fields=["status", "message", "finished_at"])
            results.append({"company": binding.company, "upserted": 0, "disabled": 0, "error": str(exc)})
    return results


def has_synced_today(integration=SyncRun.Integration.KINGDEE, company=None, on=None):
    """当天是否已有成功同步记录（命令幂等判据）。"""
    on = on or timezone.localdate()
    qs = SyncRun.objects.filter(integration=integration, status=SyncRun.Status.SUCCESS, started_at__date=on)
    if company is not None:
        qs = qs.filter(company=company)
    return qs.exists()
