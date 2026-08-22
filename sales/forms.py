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

    def __init__(self, *args, user, company, **kwargs):
        super().__init__(*args, **kwargs)
        options = customer_options_for(user, company)
        self.customer_options = [label for _, label, _ in options]
        # 标签 -> (客户, 归属人)：负责人跟着所选客户走，不取当前操作人，
        # 否则管理员代录时会误判成「客户未分配给销售负责人」。
        self._customer_lookup = {label: (customer, owner) for customer, label, owner in options}
        self.resolved_owner = None
        if self.instance and self.instance.pk and not self.is_bound:
            self.initial["customer"] = next(
                (label for customer, label, owner in options
                 if customer.pk == self.instance.customer_id and owner == self.instance.owner),
                next((label for customer, label, _ in options if customer.pk == self.instance.customer_id),
                     self.instance.customer.name),
            )

    def clean_customer(self):
        value = str(self.cleaned_data["customer"]).strip()
        found = self._customer_lookup.get(value)
        if found is None and value.isdigit():
            # 同一客户可能分给多人，按 ID 提交时无法确定负责人，只在唯一时接受。
            matches = {(customer, owner) for customer, owner in self._customer_lookup.values() if str(customer.pk) == value}
            if len(matches) == 1:
                found = matches.pop()
            elif matches:
                raise forms.ValidationError("该客户分配给多位业务员，请从候选列表中选择具体负责人")
        if found is None:
            raise forms.ValidationError("请选择列表中的客户")
        customer, owner = found
        if owner is None:
            raise forms.ValidationError("该客户还没有分配销售负责人，请先在「销售客户归属」中分配")
        self.resolved_owner = owner
        return customer
