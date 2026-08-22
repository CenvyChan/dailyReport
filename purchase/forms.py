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

    def __init__(self, *args, user, company, **kwargs):
        super().__init__(*args, **kwargs)
        options = supplier_options_for(user, company)
        self.supplier_options = [label for _, label, _ in options]
        # 标签 -> (供应商, 归属人)：负责人跟着所选供应商走，不取当前操作人，
        # 否则管理员代录时会误判成「供应商未分配给采购负责人」。
        self._supplier_lookup = {label: (supplier, owner) for supplier, label, owner in options}
        self.resolved_owner = None
        if self.instance and self.instance.pk and not self.is_bound:
            self.initial["supplier"] = next(
                (label for supplier, label, owner in options
                 if supplier.pk == self.instance.supplier_id and owner == self.instance.buyer),
                next((label for supplier, label, _ in options if supplier.pk == self.instance.supplier_id),
                     self.instance.supplier.name),
            )

    def clean_supplier(self):
        value = str(self.cleaned_data["supplier"]).strip()
        found = self._supplier_lookup.get(value)
        if found is None and value.isdigit():
            # 同一供应商可能分给多人，按 ID 提交时无法确定负责人，只在唯一时接受。
            matches = {(supplier, owner) for supplier, owner in self._supplier_lookup.values() if str(supplier.pk) == value}
            if len(matches) == 1:
                found = matches.pop()
            elif matches:
                raise forms.ValidationError("该供应商分配给多位采购员，请从候选列表中选择具体负责人")
        if found is None:
            raise forms.ValidationError("请选择列表中的供应商")
        supplier, owner = found
        if owner is None:
            raise forms.ValidationError("该供应商还没有分配采购负责人，请先在「采购供应商归属」中分配")
        self.resolved_owner = owner
        return supplier
