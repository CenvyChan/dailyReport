from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import models


class MailingList(models.Model):
    """一个公司一份收件配置，决定每天把哪家公司的数据发给谁。"""

    class Scope(models.TextChoices):
        BOTH = "BOTH", "销售和采购"
        SALES = "SALES", "仅销售"
        PURCHASE = "PURCHASE", "仅采购"

    company = models.ForeignKey(
        "core.Company", verbose_name="公司", on_delete=models.CASCADE, related_name="mailing_lists"
    )
    name = models.CharField("收件组名称", max_length=120)
    scope = models.CharField("推送内容", max_length=10, choices=Scope.choices, default=Scope.BOTH)
    recipients = models.TextField("收件人", help_text="多个邮箱用英文逗号或换行分隔。")
    cc_recipients = models.TextField("抄送", blank=True, default="")
    send_at = models.TimeField("每日发送时间", help_text="按服务器所在时区（Asia/Shanghai）触发。")
    attach_workbook = models.BooleanField("附带 Excel 明细", default=True)
    is_active = models.BooleanField("启用", default=True)

    class Meta:
        ordering = ["company", "send_at", "name"]
        verbose_name = "邮件收件组"
        verbose_name_plural = "邮件收件组"
        constraints = [
            models.UniqueConstraint(fields=["company", "name"], name="unique_mailing_list_per_company")
        ]

    def __str__(self):
        return f"{self.company} - {self.name}"

    def clean(self):
        if not self.recipient_list():
            raise ValidationError({"recipients": "至少填写一个收件人邮箱"})
        for address in self.recipient_list() + self.cc_list():
            try:
                validate_email(address)
            except ValidationError:
                raise ValidationError({"recipients": f"邮箱格式无效：{address}"}) from None

    @staticmethod
    def _split(value):
        return [part.strip() for part in (value or "").replace("\r", "\n").replace(",", "\n").split("\n") if part.strip()]

    def recipient_list(self):
        return self._split(self.recipients)

    def cc_list(self):
        return self._split(self.cc_recipients)

    @property
    def includes_sales(self):
        return self.scope in (self.Scope.BOTH, self.Scope.SALES)

    @property
    def includes_purchase(self):
        return self.scope in (self.Scope.BOTH, self.Scope.PURCHASE)


class DeliveryLog(models.Model):
    """发送留痕，追加写入。防重发靠命令查询当天是否已有 SENT 记录，
    这样 --force 补发仍然能落一条新记录。"""

    class Status(models.TextChoices):
        SENT = "SENT", "发送成功"
        FAILED = "FAILED", "发送失败"

    mailing_list = models.ForeignKey(
        MailingList, verbose_name="收件组", on_delete=models.CASCADE, related_name="delivery_logs"
    )
    report_date = models.DateField("业务日期")
    status = models.CharField("发送结果", max_length=10, choices=Status.choices)
    recipient_count = models.PositiveSmallIntegerField("收件人数", default=0)
    subject = models.CharField("邮件主题", max_length=255, blank=True, default="")
    message = models.TextField("失败原因", blank=True, default="")
    created_at = models.DateTimeField("发送时间", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "邮件发送记录"
        verbose_name_plural = "邮件发送记录"
        indexes = [
            models.Index(fields=["mailing_list", "report_date", "status"], name="delivery_lookup_idx")
        ]

    def __str__(self):
        return f"{self.report_date} {self.mailing_list} {self.get_status_display()}"
