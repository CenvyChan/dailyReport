from datetime import timedelta

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.urls import path
from django.utils import timezone

from core.admin import AuditedAdmin, _snapshot
from core.models import Company
from core.services.audit import record_audit

from .crypto import encrypt

from .models import (
    DingtalkApp,
    DingtalkCompanyMapping,
    PaymentReportDispatch,
    PaymentReportSnapshot,
    DingtalkApprovalInstance,
    DingtalkGroupConfig,
    DingtalkProcessConfig,
    KingdeeAccount,
    KingdeeFormConfig,
    KingdeeOrgBinding,
    KingdeePartyMapping,
    ReportDelivery,
    StockTransaction,
    StockTransactionLine,
    SyncRun,
)


class SecretMaskingAdmin(AuditedAdmin):
    """在 AuditedAdmin 基础上：密钥字段用密码框展示、留空保持原值、审计快照脱敏。"""

    secret_fields = ()

    def _mask(self, data):
        return {k: ("******" if k in self.secret_fields and v else v) for k, v in data.items()}

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj, change=change, **kwargs)
        for name in self.secret_fields:
            if name in form.base_fields:
                field = form.base_fields[name]
                field.widget = forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"})
                field.required = False
                field.help_text = (field.help_text or "") + "（留空表示不修改）"
        return form

    def save_model(self, request, obj, form, change):
        existing = type(obj).objects.filter(pk=obj.pk).first() if (change and obj.pk) else None
        for name in self.secret_fields:
            submitted = (form.cleaned_data.get(name) or "").strip()
            if submitted:
                setattr(obj, name, encrypt(submitted))  # 新值：加密后入库
            elif existing:
                setattr(obj, name, getattr(existing, name))  # 留空：保留原密文
        before = self._mask(_snapshot(existing)) if existing else {}
        # 跳过 AuditedAdmin.save_model 的未脱敏审计，改用脱敏快照。
        super(AuditedAdmin, self).save_model(request, obj, form, change)
        record_audit(
            actor=request.user,
            instance=obj,
            action="UPDATE" if change else "CREATE",
            before=before,
            after=self._mask(_snapshot(obj)),
        )

    def delete_model(self, request, obj):
        record_audit(actor=request.user, instance=obj, action="DELETE", before=self._mask(_snapshot(obj)), after={})
        super(AuditedAdmin, self).delete_model(request, obj)


class ReadOnlyAdmin(admin.ModelAdmin):
    """同步落库表：只读展示，不允许在后台增删改。"""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(KingdeeAccount)
class KingdeeAccountAdmin(SecretMaskingAdmin):
    secret_fields = ("app_secret",)
    list_display = ("name", "server_url", "acct_id", "username", "lcid", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "acct_id", "username")
    field_help_texts = {
        "server_url": "金蝶 WebAPI 地址，形如 http://172.16.77.77:3288/k3cloud",
        "acct_id": "数据中心 acctID。",
        "app_id": "第三方应用 AppID。",
        "app_secret": "第三方应用密钥，仅本表保存，不写入环境变量或代码。",
    }


@admin.register(KingdeeOrgBinding)
class KingdeeOrgBindingAdmin(AuditedAdmin):
    list_display = ("company", "account", "org_number", "org_name", "is_active")
    list_filter = ("account", "is_active")
    search_fields = ("company__name", "org_number", "org_name")
    field_help_texts = {
        "org_number": "该公司对应的金蝶组织编码（FStockOrgId.FNumber），用于按组织过滤单据。",
    }


@admin.register(KingdeeFormConfig)
class KingdeeFormConfigAdmin(AuditedAdmin):
    list_display = ("business_type", "form_id", "window_mode", "trailing_days", "status_filter", "is_active")
    list_filter = ("is_active", "window_mode")
    field_help_texts = {
        "form_id": "销售出库=SAL_OUTSTOCK，采购入库=STK_InStock。",
        "status_filter": "单据状态过滤，C=已审核；留空=不限状态。",
        "fld_fid": "各字段名请先用金蝶 query_metadata 核对；不同账套的自定义字段可能不同。留空的字段不查询。",
        "fld_party_number": "SAL_OUTSTOCK 表头通常无客户，可留空，或填关联销售订单上的客户字段。",
    }


@admin.register(KingdeePartyMapping)
class KingdeePartyMappingAdmin(AuditedAdmin):
    list_display = ("company", "party_type", "k3_name", "k3_number", "match_status", "resolved")
    list_filter = ("company", "party_type", "match_status")
    search_fields = ("k3_name", "k3_number")
    readonly_fields = ("candidates", "updated_at")
    autocomplete_fields = ()
    field_help_texts = {
        "customer": "PENDING/UNMATCHED 时人工在此挂接系统客户；保存后状态请改为『人工确定』。",
        "supplier": "PENDING/UNMATCHED 时人工在此挂接系统供应商；保存后状态请改为『人工确定』。",
        "candidates": "模糊匹配命中的多个待选（只读），供人工判断。",
    }

    @admin.display(description="已挂接")
    def resolved(self, obj):
        return obj.customer or obj.supplier or "—"


@admin.register(DingtalkApp)
class DingtalkAppAdmin(SecretMaskingAdmin):
    secret_fields = ("app_secret",)
    list_display = ("company", "name", "app_key", "corp_id", "is_active")
    list_filter = ("is_active",)
    search_fields = ("company__name", "name", "app_key")
    field_help_texts = {
        "app_key": "钉钉企业内部应用 AppKey；同一应用可复用到多个公司，无需重复配置。",
        "app_secret": "钉钉企业内部应用 AppSecret，仅本表保存；同一应用可复用到多个公司。",
    }


class DingtalkGroupConfigForm(forms.ModelForm):
    companies = forms.ModelMultipleChoiceField(
        label="推送公司（可多选）",
        queryset=DingtalkGroupConfig._meta.get_field("companies").remote_field.model.objects.filter(is_active=True),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="同一群聊可选择多家公司；只推送勾选的公司。",
    )
    payment_report_types = forms.MultipleChoiceField(
        label="付款报表周期", choices=[("day", "付款日报"), ("week", "付款周报（周一）"), ("month", "付款月报（每月1日）")],
        widget=forms.CheckboxSelectMultiple, required=False,
    )
    content_types = forms.MultipleChoiceField(
        label="推送内容",
        choices=DingtalkGroupConfig.ContentType.choices,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="勾选要包含的数据类型",
    )

    class Meta:
        model = DingtalkGroupConfig
        fields = "__all__"
        # enabled_at 由 save() 自动维护，不能让人手填，否则会绕过启用基线。
        exclude = ("company", "enabled_at")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 从JSONField读取已有值
        if self.instance.pk and self.instance.content_types:
            self.fields["content_types"].initial = self.instance.content_types
        if self.instance.pk and self.instance.payment_report_types:
            self.fields["payment_report_types"].initial = self.instance.payment_report_types
        if self.instance.pk and not self.instance.companies.exists() and self.instance.company_id:
            self.fields["companies"].initial = [self.instance.company_id]

    def clean(self):
        data = super().clean()
        companies = list(data.get("companies") or [])
        app = data.get("app")
        if not companies:
            raise forms.ValidationError("至少选择一个推送公司。")
        if app:
            missing = [company.name for company in companies
                       if app.company_id != company.pk
                       and not app.company_mappings.filter(company=company).exists()]
            if missing:
                raise forms.ValidationError(
                    "钉钉应用尚未映射这些公司：" + "、".join(missing)
                )
        return data


class ManualPushForm(forms.Form):
    REPORT_KIND_OPERATIONS = "operations"
    REPORT_KIND_PAYMENT_WEEK = "payment_week"
    REPORT_KIND_PAYMENT_MONTH = "payment_month"
    REPORT_KIND_CHOICES = [
        (REPORT_KIND_OPERATIONS, "运营日报（销售/采购）"),
        (REPORT_KIND_PAYMENT_WEEK, "付款周报（上一整周）"),
        (REPORT_KIND_PAYMENT_MONTH, "付款月报（上一整月）"),
    ]

    report_kind = forms.ChoiceField(
        label="报表类型",
        choices=REPORT_KIND_CHOICES,
        initial=REPORT_KIND_OPERATIONS,
        widget=forms.RadioSelect,
        help_text="运营日报与付款报表是两条独立链路："
                  "运营日报按「快照业务范围 ∩ 群推送内容」判定；"
                  "付款周报/月报按群配置的「付款报表周期」判定。",
    )
    report_date = forms.DateField(
        label="基准日期",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        input_formats=["%Y-%m-%d"],
        help_text="运营日报取该日期的快照；付款周报/月报按该日期推算「上一整周/上一整月」。",
    )
    group_configs = forms.ModelMultipleChoiceField(
        label="推送目标（群配置）",
        queryset=DingtalkGroupConfig.objects.all().order_by("name"),
        widget=forms.CheckboxSelectMultiple,
        help_text="只推送到勾选的群；停用的配置也可以手动推送。",
    )
    companies = forms.ModelMultipleChoiceField(
        label="限定公司（可选）",
        queryset=Company.objects.filter(is_active=True),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="留空 = 按群配置关联的公司全部发送。付款报表仅支持已接入付款的组织（FNS/NBHH）。",
    )
    regenerate = forms.BooleanField(
        label="发送前按当前数据重建快照",
        required=False,
        help_text="运营日报：覆盖该日期已冻结的快照。付款报表：重建该周期的付款快照（审批数据补同步后使用）。"
                  "都不会自动重发到其他群。",
    )

    def clean(self):
        data = super().clean()
        from integrations.services.payment_organizations import (
            PAYMENT_REPORT_COMPANY_CODES,
        )
        kind = data.get("report_kind")
        if kind in (self.REPORT_KIND_PAYMENT_WEEK, self.REPORT_KIND_PAYMENT_MONTH):
            allowed = set(PAYMENT_REPORT_COMPANY_CODES)
            picked = {company.code for company in (data.get("companies") or [])}
            unsupported = sorted(picked - allowed)
            if unsupported:
                raise forms.ValidationError(
                    "付款报表仅支持：" + "、".join(sorted(allowed))
                    + f"；不支持所选公司 {('、'.join(unsupported))}。"
                )
        return data


@admin.register(DingtalkGroupConfig)
class DingtalkGroupConfigAdmin(AuditedAdmin):
    form = DingtalkGroupConfigForm
    change_list_template = "admin/integrations/dingtalkgroupconfig/change_list.html"
    list_display = ("companies_display", "name", "app", "content_types_display", "send_at", "is_active", "enabled_at")
    list_filter = ("companies", "is_active")
    search_fields = ("name", "open_conversation_id")

    @admin.display(description="推送公司")
    def companies_display(self, obj):
        companies = list(obj.companies.all())
        if not companies and obj.company_id:
            companies = [obj.company]
        return "、".join(company.name for company in companies) or "-"

    @admin.display(description="推送内容")
    def content_types_display(self, obj):
        if not obj.content_types:
            return "-"
        labels = [dict(DingtalkGroupConfig.ContentType.choices).get(ct, ct) for ct in obj.content_types]
        return "、".join(labels)

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "manual-push/",
                self.admin_site.admin_view(self.manual_push_view),
                name="integrations_dingtalkgroupconfig_manual_push",
            ),
        ]
        return custom + urls

    def manual_push_view(self, request):
        if not self.has_change_permission(request):
            raise PermissionDenied

        results = []
        if request.method == "POST":
            form = ManualPushForm(request.POST)
            if form.is_valid():
                results = self._perform_manual_push(
                    request,
                    report_kind=form.cleaned_data["report_kind"],
                    report_date=form.cleaned_data["report_date"],
                    group_configs=form.cleaned_data["group_configs"],
                    only_companies=form.cleaned_data["companies"],
                    regenerate=form.cleaned_data["regenerate"],
                )
                if any(row["status"] == "SENT" for row in results):
                    self.message_user(request, "手动推送完成，请核对下方结果。", messages.SUCCESS)
                else:
                    self.message_user(request, "没有任何记录发送成功，请核对下方结果。", messages.WARNING)
        else:
            form = ManualPushForm(initial={"report_date": timezone.localdate() - timedelta(days=1)})

        context = {
            **self.admin_site.each_context(request),
            "title": "手动推送报表",
            "form": form,
            "results": results,
            "opts": self.model._meta,
        }
        return render(request, "admin/integrations/dingtalkgroupconfig/manual_push.html", context)

    def _perform_manual_push(self, request, *, report_kind, report_date, group_configs, only_companies, regenerate):
        """按报表类型分派到两条互不相通的链路。

        运营日报：ReportSnapshot + ReportDelivery，按「快照范围 ∩ 群推送内容」判定。
        付款报表：PaymentReportSnapshot + PaymentReportDispatch，按群「付款报表周期」判定，
                 实际发送复用 send_payment_report 命令（含卡片、在线快照与附件）。
        """
        if report_kind in (ManualPushForm.REPORT_KIND_PAYMENT_WEEK, ManualPushForm.REPORT_KIND_PAYMENT_MONTH):
            period = "week" if report_kind == ManualPushForm.REPORT_KIND_PAYMENT_WEEK else "month"
            rows = self._perform_payment_push(
                report_period=period,
                base_date=report_date,
                group_configs=group_configs,
                only_companies=only_companies,
                rebuild=regenerate,
            )
        else:
            rows = self._perform_operations_push(
                report_date=report_date,
                group_configs=group_configs,
                only_companies=only_companies,
                regenerate=regenerate,
            )

        record_audit(
            actor=request.user,
            instance=group_configs[0],
            action="MANUAL_PUSH",
            before={},
            after={
                "report_kind": report_kind,
                "report_date": report_date.isoformat(),
                "regenerate": regenerate,
                "group_configs": [config.id for config in group_configs],
                "companies": [company.id for company in only_companies] if only_companies else [],
                "results": rows,
            },
        )
        return rows

    def _perform_operations_push(self, *, report_date, group_configs, only_companies, regenerate):
        """运营日报链路：生成/复用运营快照后按群内容过滤投递。"""
        from integrations.models import ReportSnapshot
        from integrations.services.report_delivery import generate_report_snapshot, send_manual_report

        rows = []
        for config in group_configs:
            targets = self._push_targets(config, only_companies)
            if not targets:
                rows.append({
                    "config": config.name, "company": "—", "status": "SKIPPED",
                    "message": "群配置未关联所选公司",
                })
                continue
            for company in targets:
                try:
                    existing = ReportSnapshot.objects.filter(
                        company=company, report_date=report_date,
                    ).order_by("id").first()
                    snapshot = generate_report_snapshot(
                        company=company,
                        report_date=report_date,
                        scope=existing.scope if existing else "BOTH",
                        force_regenerate=regenerate,
                    )
                    results = send_manual_report(snapshot, [config])
                    if not results:
                        rows.append({
                            "config": config.name, "company": company.name,
                            "status": "SKIPPED",
                            "message": "群配置未勾选该快照包含的业务内容",
                        })
                    for _channel, status, message in results:
                        rows.append({
                            "config": config.name, "company": company.name,
                            "status": status, "message": message,
                        })
                except Exception as exc:  # 单条失败不阻断其他目标
                    rows.append({
                        "config": config.name, "company": company.name,
                        "status": "FAILED", "message": str(exc),
                    })
        return rows

    def _perform_payment_push(self, *, report_period, base_date, group_configs, only_companies, rebuild):
        """付款报表链路：逐 (群, 公司) 调用 send_payment_report，成功/失败都落一行结果。

        与定时链路的关键差异：
        - PaymentReportDispatch 唯一键含 delivery_date，手动补发不能用「今天」作为
          delivery_date（当天可能已自动发过，get_or_create 会直接跳过），
          因此手动改用 update_or_create 复用当天回执行并覆盖状态，绝不重复建行。
        - 发送复用 send_payment_report 命令，卡片/在线快照/附件行为与定时完全一致。
        """
        from io import StringIO

        from django.core.management import call_command

        from integrations.models import PaymentReportDispatch
        from integrations.services.payment_organizations import PAYMENT_REPORT_COMPANY_CODES

        period_label = {"week": "付款周报", "month": "付款月报"}[report_period]
        allowed_codes = set(PAYMENT_REPORT_COMPANY_CODES)
        rows = []

        for config in group_configs:
            targets = [
                company for company in self._push_targets(config, only_companies)
                if company.code in allowed_codes
            ]
            if not targets:
                rows.append({
                    "config": config.name, "company": "—", "status": "SKIPPED",
                    "message": f"该群没有可用于{period_label}的组织（仅支持 "
                               + "、".join(sorted(allowed_codes)) + "）",
                })
                continue
            for company in targets:
                if report_period not in (config.payment_report_types or []):
                    rows.append({
                        "config": config.name, "company": company.name,
                        "status": "SKIPPED",
                        "message": f"群配置未勾选「{period_label}」，"
                                   "请在群配置的「付款报表周期」中勾选后重试。",
                    })
                    continue
                dispatch, _created = PaymentReportDispatch.objects.update_or_create(
                    group=config,
                    company=company,
                    report_type=report_period,
                    delivery_date=base_date,
                    defaults={"status": "RUNNING", "error": ""},
                )
                buffer = StringIO()
                try:
                    call_command(
                        "send_payment_report",
                        report_period,
                        company=company.code,
                        app_id=config.app_id,
                        group_id=config.open_conversation_id,
                        base_date=base_date.isoformat(),
                        force_snapshot=rebuild,
                        stdout=buffer,
                    )
                    dispatch.status = "SENT"
                    dispatch.error = ""
                except Exception as exc:  # 单条失败不阻断其他目标
                    dispatch.status = "FAILED"
                    dispatch.error = str(exc)
                    rows.append({
                        "config": config.name, "company": company.name,
                        "status": "FAILED", "message": str(exc),
                    })
                else:
                    rows.append({
                        "config": config.name, "company": company.name,
                        "status": "SENT",
                        "message": f"{period_label}已发送（基准日期 {base_date.isoformat()}）",
                    })
                finally:
                    dispatch.save(update_fields=["status", "error", "updated_at"])
        return rows

    @staticmethod
    def _push_targets(config, only_companies):
        """群配置关联的公司；旧的单公司字段作为兜底。"""
        targets = list(config.companies.all())
        if not targets and config.company_id:
            targets = [config.company]
        if only_companies:
            targets = [company for company in targets if company in only_companies]
        return targets


@admin.register(ReportDelivery)
class ReportDeliveryAdmin(ReadOnlyAdmin):
    list_display = ("snapshot", "channel", "target_display", "status", "attempt_count", "sent_at")
    list_filter = ("channel", "status")
    search_fields = ("target_display", "target_identifier", "last_error")
    readonly_fields = [f.name for f in ReportDelivery._meta.fields]


@admin.register(DingtalkProcessConfig)
class DingtalkProcessConfigAdmin(AuditedAdmin):
    list_display = ("app", "name", "process_code", "amount_component", "lookback_days", "is_active")
    list_filter = ("app", "is_active")
    search_fields = ("name", "process_code")
    field_help_texts = {
        "process_code": "钉钉审批模板 process_code（如『付款申请』模板）。",
        "amount_component": "表单中付款金额字段的组件名/标题，用于提取金额做应付/已付统计。",
    }


class StockTransactionLineInline(admin.TabularInline):
    model = StockTransactionLine
    extra = 0
    can_delete = False
    readonly_fields = ("entry_id", "seq", "material_number", "material_name", "quantity", "unit", "unit_price", "amount")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(StockTransaction)
class StockTransactionAdmin(ReadOnlyAdmin):
    list_display = ("company", "business_type", "bill_no", "biz_date", "doc_status", "total_quantity", "total_amount", "is_active")
    list_filter = ("company", "business_type", "is_active", "biz_date")
    search_fields = ("bill_no", "fid", "k3_party_name")
    date_hierarchy = "biz_date"
    inlines = [StockTransactionLineInline]
    readonly_fields = [f.name for f in StockTransaction._meta.fields]


@admin.register(DingtalkApprovalInstance)
class DingtalkApprovalInstanceAdmin(ReadOnlyAdmin):
    list_display = ("company", "process_name", "title", "originator_name", "status", "result", "amount", "create_time")
    list_filter = ("company", "process_code", "status", "result")
    search_fields = ("title", "process_instance_id", "originator_name")
    date_hierarchy = "create_time"
    readonly_fields = [f.name for f in DingtalkApprovalInstance._meta.fields]


@admin.register(SyncRun)
class SyncRunAdmin(ReadOnlyAdmin):
    list_display = ("integration", "company", "status", "window_start", "window_end", "rows_upserted", "rows_disabled", "started_at", "finished_at")
    list_filter = ("integration", "status", "company")
    date_hierarchy = "started_at"
    readonly_fields = [f.name for f in SyncRun._meta.fields]


@admin.register(DingtalkCompanyMapping)
class DingtalkCompanyMappingAdmin(AuditedAdmin):
    list_display = ("app", "application_company", "company")
    list_filter = ("app", "company")
    search_fields = ("application_company", "company__name")


@admin.register(PaymentReportDispatch)
class PaymentReportDispatchAdmin(ReadOnlyAdmin):
    list_display = ("group", "company", "report_type", "delivery_date", "status", "updated_at")
    list_filter = ("status", "report_type")
    readonly_fields = [f.name for f in PaymentReportDispatch._meta.fields]


@admin.register(PaymentReportSnapshot)
class PaymentReportSnapshotAdmin(ReadOnlyAdmin):
    list_display = ("company", "report_type", "period_label", "period_start", "period_end", "generated_at")
    list_filter = ("company", "report_type")
    search_fields = ("period_label", "process_code")
    date_hierarchy = "period_start"
    readonly_fields = [f.name for f in PaymentReportSnapshot._meta.fields]
