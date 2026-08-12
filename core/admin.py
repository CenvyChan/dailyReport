import json
from datetime import date, datetime
from decimal import Decimal

from django.contrib import admin
from django.apps import apps
from django.contrib.auth.admin import GroupAdmin as DjangoGroupAdmin
from django.contrib.auth.models import Group
from django.db.models import Count, Model
from django.forms.models import model_to_dict
from django.utils.html import format_html

from core.models import Customer, ExchangeRate, OperationLog, PurchaseAssignment, SalesAssignment, Supplier
from core.services.audit import record_audit
from core.services.users import ROLE_LABELS, role_label
from purchase.models import PurchaseReceipt
from sales.models import SalesShipment


admin.site.site_header = "轻量日报系统管理"
admin.site.site_title = "轻量日报管理"
admin.site.index_title = "系统配置与数据维护"
apps.get_app_config("auth").verbose_name = "用户与权限"

ACTION_LABELS = {
    "CREATE": "新增",
    "UPDATE": "修改",
    "DELETE": "删除",
    "IMPORT": "导入",
    "PASSWORD_RESET": "重置密码",
    "MIGRATION_CREATE": "系统初始化",
}
MODEL_LABELS = {
    "core.Customer": "客户",
    "core.Supplier": "供应商",
    "core.SalesAssignment": "销售客户归属",
    "core.PurchaseAssignment": "采购供应商归属",
    "core.ExchangeRate": "月度汇率",
    "auth.User": "用户",
    "auth.Group": "业务角色",
    "sales.SalesShipment": "销售日报",
    "purchase.PurchaseReceipt": "采购日报",
}
MODEL_CLASSES = {
    model._meta.label: model
    for model in (
        Customer,
        Supplier,
        SalesAssignment,
        PurchaseAssignment,
        ExchangeRate,
        SalesShipment,
        PurchaseReceipt,
    )
}
EXTRA_FIELD_LABELS = {
    ("auth.User", "username"): "用户名",
    ("auth.User", "first_name"): "姓名",
    ("auth.User", "role"): "角色",
    ("auth.User", "must_change_password"): "首次登录必须改密",
}
ROLE_DESCRIPTIONS = {
    "administrator": "维护用户、汇率和基础资料，并查看全部销售采购数据",
    "sales": "填写并查看本人负责客户的销售日报",
    "purchase": "填写并查看本人负责供应商的采购日报",
    "report_viewer": "只查看销售和采购分析报表",
}


def action_label(action):
    return ACTION_LABELS.get(action, action)


def _json_value(value):
    if isinstance(value, Model):
        return value.pk
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _snapshot(instance):
    return {key: _json_value(value) for key, value in model_to_dict(instance).items()}


def _field_label(model_label, field_name):
    if (model_label, field_name) in EXTRA_FIELD_LABELS:
        return EXTRA_FIELD_LABELS[(model_label, field_name)]
    model = MODEL_CLASSES.get(model_label)
    if model is None:
        return field_name
    try:
        return str(model._meta.get_field(field_name).verbose_name)
    except Exception:
        return field_name


def _readable_value(model_label, field_name, value):
    if isinstance(value, bool):
        return "是" if value else "否"
    if model_label == "auth.User" and field_name == "role":
        return role_label(value)
    model = MODEL_CLASSES.get(model_label)
    if model is None:
        return value
    try:
        field = model._meta.get_field(field_name)
    except Exception:
        return value
    choices = dict(field.flatchoices)
    if value in choices:
        return str(choices[value])
    if field.is_relation and value not in (None, ""):
        return f"数据编号 {value}"
    return value


def _readable_snapshot(model_label, data):
    return {
        _field_label(model_label, field_name): _readable_value(model_label, field_name, value)
        for field_name, value in data.items()
    }


class AuditedAdmin(admin.ModelAdmin):
    field_help_texts = {}

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj, change, **kwargs)
        for field_name, help_text in self.field_help_texts.items():
            if field_name in form.base_fields:
                form.base_fields[field_name].help_text = help_text
        return form

    def save_model(self, request, obj, form, change):
        before = _snapshot(type(obj).objects.get(pk=obj.pk)) if change else {}
        super().save_model(request, obj, form, change)
        record_audit(actor=request.user, instance=obj, action="UPDATE" if change else "CREATE", before=before, after=_snapshot(obj))

    def delete_model(self, request, obj):
        record_audit(actor=request.user, instance=obj, action="DELETE", before=_snapshot(obj), after={})
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            record_audit(actor=request.user, instance=obj, action="DELETE", before=_snapshot(obj), after={})
        super().delete_queryset(request, queryset)


admin.site.unregister(Group)


@admin.register(Group)
class RoleGroupAdmin(DjangoGroupAdmin):
    list_display = ("name", "role_chinese", "role_description", "member_count")

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_member_count=Count("user"))

    @admin.display(description="中文角色")
    def role_chinese(self, obj):
        return ROLE_LABELS.get(obj.name, "自定义角色")

    @admin.display(description="角色说明")
    def role_description(self, obj):
        return ROLE_DESCRIPTIONS.get(obj.name, "自定义权限组")

    @admin.display(description="用户数", ordering="_member_count")
    def member_count(self, obj):
        return obj._member_count

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Customer)
class CustomerAdmin(AuditedAdmin):
    list_display = ("name", "is_active")
    search_fields = ("name",)
    field_help_texts = {
        "name": "用于销售日报选择和报表汇总；请使用公司统一的客户全称。",
        "is_active": "停用后保留历史数据，但不再用于新增销售日报。",
    }


@admin.register(Supplier)
class SupplierAdmin(AuditedAdmin):
    list_display = ("name", "is_active")
    search_fields = ("name",)
    field_help_texts = {
        "name": "用于采购日报选择和报表汇总；请使用公司统一的供应商全称。",
        "is_active": "停用后保留历史数据，但不再用于新增采购日报。",
    }


@admin.register(SalesAssignment)
class SalesAssignmentAdmin(AuditedAdmin):
    list_display = ("user", "customer")
    search_fields = ("user__username", "customer__name")
    field_help_texts = {
        "user": "选择负责该客户的销售业务员。",
        "customer": "归属后，该业务员才能在销售日报中选择和查看此客户。",
    }


@admin.register(PurchaseAssignment)
class PurchaseAssignmentAdmin(AuditedAdmin):
    list_display = ("user", "supplier")
    search_fields = ("user__username", "supplier__name")
    field_help_texts = {
        "user": "选择负责该供应商的采购员。",
        "supplier": "归属后，该采购员才能在采购日报中选择和查看此供应商。",
    }


@admin.register(ExchangeRate)
class ExchangeRateAdmin(AuditedAdmin):
    list_display = ("month", "usd_to_cny")
    field_help_texts = {
        "month": "请选择对应月份的 1 日；系统按日报日期所在月份匹配汇率。",
        "usd_to_cny": "填写 1 美元可兑换的人民币金额；日报保存后会保留当时的汇率快照。",
    }


@admin.register(OperationLog)
class OperationLogAdmin(admin.ModelAdmin):
    readonly_fields = [field.name for field in OperationLog._meta.fields] + ["operation_summary", "action_chinese", "model_chinese", "before_readable", "after_readable"]
    list_display = ("created_at", "operation_summary", "actor", "action_chinese", "model_chinese", "object_id")
    list_filter = ("action", "model_label", "created_at")
    search_fields = ("actor__username", "object_id")
    fields = ("created_at", "operation_summary", "actor", "action_chinese", "model_chinese", "object_id", "before_readable", "after_readable")

    @admin.display(description="操作说明")
    def operation_summary(self, obj):
        actor = obj.actor.username if obj.actor else "系统"
        return f"{actor} {action_label(obj.action)}了{MODEL_LABELS.get(obj.model_label, obj.model_label)}（数据编号：{obj.object_id}）"

    @admin.display(description="操作")
    def action_chinese(self, obj):
        return action_label(obj.action)

    @admin.display(description="数据类型")
    def model_chinese(self, obj):
        return MODEL_LABELS.get(obj.model_label, obj.model_label)

    @admin.display(description="变更前（字段和值）")
    def before_readable(self, obj):
        data = _readable_snapshot(obj.model_label, obj.before_data)
        if not data:
            return "无"
        return format_html("<pre style='white-space:pre-wrap'>{}</pre>", json.dumps(data, ensure_ascii=False, indent=2))

    @admin.display(description="变更后（字段和值）")
    def after_readable(self, obj):
        data = _readable_snapshot(obj.model_label, obj.after_data)
        if not data:
            return "无"
        return format_html("<pre style='white-space:pre-wrap'>{}</pre>", json.dumps(data, ensure_ascii=False, indent=2))

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
