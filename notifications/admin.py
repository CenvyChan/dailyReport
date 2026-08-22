from django.contrib import admin

from core.admin import AuditedAdmin
from notifications.models import DeliveryLog, MailingList


@admin.register(MailingList)
class MailingListAdmin(AuditedAdmin):
    list_display = ("name", "company", "scope_chinese", "send_at", "attach_workbook", "is_active")
    list_filter = ("company", "scope", "is_active")
    search_fields = ("name", "recipients")
    field_help_texts = {
        "company": "只推送这家公司的数据；两家公司要各自建收件组。",
        "name": "例如「A 公司管理层日报」，同一公司内不能重名。",
        "scope": "决定邮件里包含销售、采购还是两者。",
        "recipients": "多个邮箱用英文逗号或换行分隔。",
        "cc_recipients": "可留空。",
        "send_at": "每天到点后由计划任务触发；同一天只会成功发送一次。",
        "attach_workbook": "勾选后附带当日明细的 Excel 文件。",
        "is_active": "停用后不再发送，历史发送记录保留。",
    }

    @admin.display(description="推送内容")
    def scope_chinese(self, obj):
        return obj.get_scope_display()


@admin.register(DeliveryLog)
class DeliveryLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "report_date", "mailing_list", "status_chinese", "recipient_count", "message")
    list_filter = ("status", "report_date", "mailing_list__company")
    search_fields = ("subject", "message")
    readonly_fields = [field.name for field in DeliveryLog._meta.fields]

    @admin.display(description="发送结果")
    def status_chinese(self, obj):
        return obj.get_status_display()

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
