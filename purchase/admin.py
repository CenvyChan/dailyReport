from django.contrib import admin

from core.admin import AuditedAdmin
from purchase.models import PurchaseReceipt


@admin.register(PurchaseReceipt)
class PurchaseReceiptAdmin(AuditedAdmin):
    list_display = ("purchase_date", "company", "supplier", "buyer", "purchase_type_chinese", "quantity", "original_amount", "amount_cny")
    list_filter = ("company", "purchase_type", "purchase_date")
    search_fields = ("supplier__name", "buyer__username")
    field_help_texts = {
        "company": "日报归属公司；A、B 两家公司的日报数据完全隔离。",
        "supplier": "选择实际入库供应商；可选范围由采购供应商归属决定。",
        "buyer": "显示并记录负责该供应商的采购员。",
        "purchase_type": "国内采购使用人民币；国外采购使用美元并匹配采购月份的汇率。",
        "original_amount": "填写原币金额，人民币折算金额由业务流程计算。",
        "exchange_rate": "录入时保存的汇率快照，历史记录通常不要手工修改。",
        "amount_cny": "按原币金额和汇率快照折算的人民币金额。",
        "source": "用于区分手工录入和历史数据导入，通常无需修改。",
    }

    @admin.display(description="采购类型")
    def purchase_type_chinese(self, obj):
        return obj.get_purchase_type_display()
