from django import forms
from django.contrib import admin

from core.admin import AuditedAdmin, _snapshot
from core.services.audit import record_audit

from .crypto import encrypt

from .models import (
    DingtalkApp,
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
        "app_key": "钉钉企业内部应用 AppKey。",
        "app_secret": "钉钉企业内部应用 AppSecret，仅本表保存。",
    }


class DingtalkGroupConfigForm(forms.ModelForm):
    class Meta:
        model = DingtalkGroupConfig
        fields = "__all__"

    def clean(self):
        data = super().clean()
        company, app = data.get("company"), data.get("app")
        if company and app and app.company_id != company.pk:
            raise forms.ValidationError("钉钉应用所属公司必须与群配置公司一致。")
        return data


@admin.register(DingtalkGroupConfig)
class DingtalkGroupConfigAdmin(AuditedAdmin):
    form = DingtalkGroupConfigForm
    list_display = ("company", "name", "app", "scope", "send_at", "is_active")
    list_filter = ("company", "scope", "is_active")
    search_fields = ("name", "open_conversation_id")


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
