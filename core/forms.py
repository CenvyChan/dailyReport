from django import forms
from django.contrib.auth.models import User

from core.models import ExchangeRate
from core.services.users import ROLE_CHOICES


class ExchangeRateForm(forms.ModelForm):
    class Meta:
        model = ExchangeRate
        fields = ["month", "usd_to_cny"]
        widgets = {"month": forms.DateInput(attrs={"type": "date"})}
        help_texts = {
            "month": "请选择对应月份的 1 日，例如 2026-08-01；每个月只维护一条汇率。",
            "usd_to_cny": "填写 1 美元可兑换的人民币金额，例如 7.1200。",
        }

    def clean_month(self):
        month = self.cleaned_data["month"]
        if month.day != 1:
            raise forms.ValidationError("汇率月份必须选择当月 1 日")
        existing = ExchangeRate.objects.filter(month=month)
        if self.instance.pk:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise forms.ValidationError("该月份汇率已存在，请直接编辑原记录")
        return month


class UserCreateForm(forms.Form):
    username = forms.CharField(label="用户名", max_length=150, help_text="建议使用工号或姓名拼音，创建后不再重复使用。")
    first_name = forms.CharField(label="姓名", max_length=150, required=False)
    role = forms.ChoiceField(label="角色", choices=ROLE_CHOICES)
    password = forms.CharField(
        label="初始密码",
        widget=forms.PasswordInput,
        help_text="此密码仅用于首次登录；用户首次登录后必须自行修改。",
    )

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("用户名已存在，请更换后再保存")
        return username


class UserPasswordResetForm(forms.Form):
    password = forms.CharField(
        label="新初始密码",
        widget=forms.PasswordInput,
        help_text="重置后，用户下次登录会被要求自行修改密码。",
    )
