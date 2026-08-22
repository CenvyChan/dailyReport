from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Company(models.Model):
    code = models.SlugField("公司代码", max_length=20, unique=True)
    name = models.CharField("公司名称", max_length=120, unique=True)
    is_active = models.BooleanField("启用", default=True)
    sort_order = models.PositiveSmallIntegerField("排序", default=0)

    class Meta:
        ordering = ["sort_order", "code"]
        verbose_name = "公司"
        verbose_name_plural = "公司"

    def __str__(self):
        return self.name


class CompanyMembership(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="用户", on_delete=models.CASCADE)
    company = models.ForeignKey(Company, verbose_name="公司", on_delete=models.CASCADE)

    class Meta:
        verbose_name = "用户公司授权"
        verbose_name_plural = "用户公司授权"
        constraints = [
            models.UniqueConstraint(fields=["user", "company"], name="unique_company_membership")
        ]

    def __str__(self):
        return f"{self.user} → {self.company}"


class Customer(models.Model):
    company = models.ForeignKey(Company, verbose_name="公司", on_delete=models.PROTECT, related_name="customers")
    name = models.CharField("客户名称", max_length=120)
    is_active = models.BooleanField("启用", default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "客户"
        verbose_name_plural = "客户"
        constraints = [
            models.UniqueConstraint(fields=["company", "name"], name="unique_customer_per_company")
        ]

    def __str__(self):
        return self.name


class Supplier(models.Model):
    company = models.ForeignKey(Company, verbose_name="公司", on_delete=models.PROTECT, related_name="suppliers")
    name = models.CharField("供应商名称", max_length=120)
    is_active = models.BooleanField("启用", default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "供应商"
        verbose_name_plural = "供应商"
        constraints = [
            models.UniqueConstraint(fields=["company", "name"], name="unique_supplier_per_company")
        ]

    def __str__(self):
        return self.name


class SalesAssignment(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="销售业务员", on_delete=models.CASCADE)
    customer = models.ForeignKey(Customer, verbose_name="客户", on_delete=models.CASCADE)

    class Meta:
        verbose_name = "销售客户归属"
        verbose_name_plural = "销售客户归属"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "customer"], name="unique_sales_assignment"
            )
        ]

    def __str__(self):
        return f"{self.user} → {self.customer}"


class PurchaseAssignment(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="采购员", on_delete=models.CASCADE)
    supplier = models.ForeignKey(Supplier, verbose_name="供应商", on_delete=models.CASCADE)

    class Meta:
        verbose_name = "采购供应商归属"
        verbose_name_plural = "采购供应商归属"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "supplier"], name="unique_purchase_assignment"
            )
        ]

    def __str__(self):
        return f"{self.user} → {self.supplier}"


class ExchangeRate(models.Model):
    company = models.ForeignKey(Company, verbose_name="公司", on_delete=models.PROTECT, related_name="exchange_rates")
    month = models.DateField("月份")
    usd_to_cny = models.DecimalField("美元兑人民币", max_digits=10, decimal_places=4)

    class Meta:
        ordering = ["-month"]
        verbose_name = "月度汇率"
        verbose_name_plural = "月度汇率"
        constraints = [
            models.UniqueConstraint(fields=["company", "month"], name="unique_exchange_rate_per_company")
        ]

    def clean(self):
        if self.month is not None and self.month.day != 1:
            raise ValidationError("汇率月份必须保存为当月 1 日")
        if self.usd_to_cny is not None and self.usd_to_cny <= 0:
            raise ValidationError("汇率必须大于 0")

    def __str__(self):
        return f"{self.month:%Y年%m月}：1 美元 = {self.usd_to_cny} 人民币"


class OperationLog(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="操作人", null=True, blank=True, on_delete=models.SET_NULL
    )
    action = models.CharField("操作类型", max_length=20)
    model_label = models.CharField("数据类型", max_length=120)
    object_id = models.CharField("数据编号", max_length=64)
    before_data = models.JSONField("变更前", default=dict)
    after_data = models.JSONField("变更后", default=dict)
    created_at = models.DateTimeField("操作时间", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "操作日志"
        verbose_name_plural = "操作日志"

    def __str__(self):
        if self.created_at:
            return f"{self.created_at:%Y-%m-%d %H:%M} 的操作日志"
        return "操作日志"


class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, verbose_name="用户", on_delete=models.CASCADE, related_name="daily_report_profile")
    must_change_password = models.BooleanField("首次登录必须改密", default=False)

    class Meta:
        verbose_name = "用户日报设置"
        verbose_name_plural = "用户日报设置"

    def __str__(self):
        return f"{self.user} 的日报设置"
