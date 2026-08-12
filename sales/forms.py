from django import forms

from core.services.permissions import customer_options_for
from sales.models import SalesShipment


class SalesShipmentForm(forms.ModelForm):
    customer = forms.CharField(
        label="客户",
        help_text="可输入客户名称或销售业务员进行筛选，然后从候选列表中选择。",
        widget=forms.TextInput(attrs={"list": "sales-customer-options", "autocomplete": "off"}),
    )

    class Meta:
        model = SalesShipment
        fields = ["customer", "sale_type", "shipment_date", "quantity", "original_amount"]
        widgets = {"shipment_date": forms.DateInput(attrs={"type": "date"})}
        help_texts = {
            "sale_type": "内销使用人民币，外销使用美元并自动匹配当月汇率。",
            "shipment_date": "汇率按出货日期所在月份匹配。",
            "quantity": "填写本次实际出货数量。",
            "original_amount": "填写原币金额，无需自行换算人民币。",
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        options = customer_options_for(user)
        self.customer_options = [label for _, label in options]
        self._customer_lookup = {label: customer for customer, label in options}
        if self.instance and self.instance.pk and not self.is_bound:
            self.initial["customer"] = next((label for customer, label in options if customer.pk == self.instance.customer_id), self.instance.customer.name)

    def clean_customer(self):
        value = str(self.cleaned_data["customer"]).strip()
        customer = self._customer_lookup.get(value)
        if customer is None and value.isdigit():
            customer = next((item for item in self._customer_lookup.values() if str(item.pk) == value), None)
        if customer is None:
            raise forms.ValidationError("请选择列表中的客户")
        return customer
