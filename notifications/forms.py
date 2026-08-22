from django import forms

from notifications.models import MailingList


class MailingListForm(forms.ModelForm):
    class Meta:
        model = MailingList
        fields = ["name", "scope", "recipients", "cc_recipients", "send_at", "attach_workbook", "is_active"]
        widgets = {
            "recipients": forms.Textarea(attrs={"rows": 4}),
            "cc_recipients": forms.Textarea(attrs={"rows": 2}),
            "send_at": forms.TimeInput(attrs={"type": "time"}),
        }
        help_texts = {
            "name": "例如「管理层日报」；同一公司内不能重名。",
            "scope": "决定邮件里包含销售、采购还是两者。",
            "recipients": "多个邮箱用英文逗号或换行分隔。",
            "cc_recipients": "可留空。",
            "send_at": "每天到这个时间后由计划任务发送；同一天只会成功发送一次。",
            "attach_workbook": "附带当日明细的 Excel 文件。",
        }

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.company = company
        self.company = company

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        existing = MailingList.objects.filter(company=self.company, name=name)
        if self.instance.pk:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise forms.ValidationError("该公司下已存在同名收件组")
        return name
