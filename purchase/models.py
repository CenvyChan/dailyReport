from django.conf import settings
from django.db import models


class PurchaseReceipt(models.Model):
    class PurchaseType(models.TextChoices):
        DOMESTIC = "DOMESTIC", "国内采购"
        FOREIGN = "FOREIGN", "国外采购"

    class DataSource(models.TextChoices):
        MANUAL = "MANUAL", "手工录入"
        HISTORY_IMPORT = "HISTORY_IMPORT", "历史数据导入"

    supplier = models.ForeignKey("core.Supplier", verbose_name="供应商", on_delete=models.PROTECT)
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="采购员", on_delete=models.PROTECT)
    purchase_type = models.CharField("采购类型", max_length=10, choices=PurchaseType.choices)
    purchase_date = models.DateField("采购日期")
    quantity = models.PositiveIntegerField("数量")
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
        db_table = "purchase_receipts"
        ordering = ["-purchase_date", "-id"]
        verbose_name = "采购日报"
        verbose_name_plural = "采购日报"

    def __str__(self):
        return f"{self.purchase_date} {self.supplier} 采购日报"
