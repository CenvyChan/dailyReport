from django.contrib import admin

from core.admin import AuditedAdmin
from sales.models import SalesShipment


@admin.register(SalesShipment)
class SalesShipmentAdmin(AuditedAdmin):
    list_display = ("shipment_date", "company", "customer", "owner", "sale_type_chinese", "quantity", "original_amount", "amount_cny")
    list_filter = ("company", "sale_type", "shipment_date")
    search_fields = ("customer__name", "owner__username")
    field_help_texts = {
        "company": "日报归属公司；A、B 两家公司的日报数据完全隔离。",
        "customer": "选择实际出货客户；可选范围由销售客户归属决定。",
        "owner": "显示并记录负责该客户的销售业务员。",
        "sale_type": "内销使用人民币；外销使用美元并匹配出货月份的汇率。",
        "original_amount": "填写原币金额，人民币折算金额由业务流程计算。",
        "exchange_rate": "录入时保存的汇率快照，历史记录通常不要手工修改。",
        "amount_cny": "按原币金额和汇率快照折算的人民币金额。",
        "source": "用于区分手工录入和历史数据导入，通常无需修改。",
    }

    @admin.display(description="销售类型")
    def sale_type_chinese(self, obj):
        return obj.get_sale_type_display()
