from django import forms

from core.services.permissions import supplier_options_for
from purchase.models import PurchaseReceipt


class PurchaseReceiptForm(forms.ModelForm):
    supplier = forms.CharField(
        label="供应商",
        help_text="可输入供应商名称或采购员进行筛选，然后从候选列表中选择。",
        widget=forms.TextInput(attrs={"list": "purchase-supplier-options", "autocomplete": "off"}),
    )

    class Meta:
        model = PurchaseReceipt
        fields = ["supplier", "purchase_type", "purchase_date", "quantity", "original_amount"]
        widgets = {"purchase_date": forms.DateInput(attrs={"type": "date"})}
        help_texts = {
            "purchase_type": "国内采购使用人民币，国外采购使用美元并自动匹配当月汇率。",
            "purchase_date": "汇率按采购日期所在月份匹配。",
            "quantity": "填写本次实际入库数量。",
            "original_amount": "填写原币金额，无需自行换算人民币。",
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        options = supplier_options_for(user)
        self.supplier_options = [label for _, label in options]
        self._supplier_lookup = {label: supplier for supplier, label in options}
        if self.instance and self.instance.pk and not self.is_bound:
            self.initial["supplier"] = next((label for supplier, label in options if supplier.pk == self.instance.supplier_id), self.instance.supplier.name)

    def clean_supplier(self):
        value = str(self.cleaned_data["supplier"]).strip()
        supplier = self._supplier_lookup.get(value)
        if supplier is None and value.isdigit():
            supplier = next((item for item in self._supplier_lookup.values() if str(item.pk) == value), None)
        if supplier is None:
            raise forms.ValidationError("请选择列表中的供应商")
        return supplier
