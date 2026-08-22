from django.conf import settings
from django.db import models


class SalesShipment(models.Model):
    class SaleType(models.TextChoices):
        DOMESTIC = "DOMESTIC", "内销"
        EXPORT = "EXPORT", "外销"

    class DataSource(models.TextChoices):
        MANUAL = "MANUAL", "手工录入"
        HISTORY_IMPORT = "HISTORY_IMPORT", "历史数据导入"

    company = models.ForeignKey("core.Company", verbose_name="公司", on_delete=models.PROTECT, related_name="sales_shipments")
    customer = models.ForeignKey("core.Customer", verbose_name="客户", on_delete=models.PROTECT)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="销售业务员", on_delete=models.PROTECT)
    sale_type = models.CharField("销售类型", max_length=10, choices=SaleType.choices)
    shipment_date = models.DateField("出货日期")
    quantity = models.DecimalField("数量", max_digits=18, decimal_places=3)
    currency = models.CharField("币种", max_length=3, editable=False)
    original_amount = models.DecimalField("原币金额", max_digits=18, decimal_places=6)
    exchange_rate = models.DecimalField("汇率快照", max_digits=10, decimal_places=4)
    amount_cny = models.DecimalField("折算人民币金额", max_digits=18, decimal_places=6)
    source = models.CharField("数据来源", max_length=20, choices=DataSource.choices, default=DataSource.MANUAL)
    source_file = models.CharField("来源文件", max_length=255, blank=True, default="")
    import_batch = models.UUIDField("导入批次", null=True, blank=True)
    source_row = models.PositiveIntegerField("来源行号", null=True, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "sales_shipments"
        ordering = ["-shipment_date", "-id"]
        verbose_name = "销售日报"
        verbose_name_plural = "销售日报"
        # 列表页和报表都是「按公司过滤 + 按日期倒序」，方向与 ordering 一致才能
        # 免掉临时排序。第二条给普通业务员用：他们的查询还会叠加 owner。
        indexes = [
            models.Index(fields=["company", "-shipment_date", "-id"], name="ss_company_date_idx"),
            models.Index(fields=["company", "owner", "-shipment_date"], name="ss_company_owner_idx"),
        ]

    def __str__(self):
        return f"{self.shipment_date} {self.customer} 销售日报"
