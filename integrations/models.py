from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        abstract = True


class KingdeeAccount(TimeStampedModel):
    """金蝶云星空连接账套凭证。应用运行时以本表为准，不读环境变量。"""

    name = models.CharField("账套名称", max_length=120, unique=True)
    server_url = models.CharField("服务地址", max_length=255, help_text="形如 http://172.16.77.77:3288/k3cloud")
    acct_id = models.CharField("数据中心ID", max_length=64)
    username = models.CharField("集成用户", max_length=64)
    app_id = models.CharField("AppID", max_length=128)
    app_secret = models.CharField("AppSecret", max_length=255)
    lcid = models.PositiveIntegerField("语言LCID", default=2052)
    is_active = models.BooleanField("启用", default=True)

    class Meta:
        verbose_name = "金蝶连接账套"
        verbose_name_plural = "金蝶连接账套"
        ordering = ["name"]

    def __str__(self):
        return self.name


class KingdeeOrgBinding(TimeStampedModel):
    """公司 ↔ 金蝶组织 绑定。一个账套可挂多个组织（多公司/多组织都通过多行承载）。"""

    company = models.OneToOneField(
        "core.Company", verbose_name="公司", on_delete=models.CASCADE, related_name="kingdee_binding"
    )
    account = models.ForeignKey(
        KingdeeAccount, verbose_name="连接账套", on_delete=models.PROTECT, related_name="org_bindings"
    )
    org_number = models.CharField("组织编码", max_length=64, help_text="金蝶组织 FStockOrgId.FNumber，用于过滤该公司的单据")
    org_name = models.CharField("组织名称", max_length=120, blank=True, default="")
    is_active = models.BooleanField("启用", default=True)

    class Meta:
        verbose_name = "公司-金蝶组织绑定"
        verbose_name_plural = "公司-金蝶组织绑定"
        ordering = ["company"]

    def __str__(self):
        return f"{self.company} → {self.org_number}"


class BusinessType(models.TextChoices):
    SALES_OUT = "SALES_OUT", "销售出库"
    PURCHASE_IN = "PURCHASE_IN", "采购入库"


class KingdeeFormConfig(TimeStampedModel):
    """按业务类型维护取哪张表单、取哪些字段。字段名需用 query_metadata 核对后填写。"""

    class WindowMode(models.TextChoices):
        CURRENT_MONTH = "CURRENT_MONTH", "当前月份"
        TRAILING_DAYS = "TRAILING_DAYS", "滚动N天"

    business_type = models.CharField("业务类型", max_length=20, choices=BusinessType.choices, unique=True)
    form_id = models.CharField("表单ID", max_length=64, help_text="销售出库=SAL_OUTSTOCK，采购入库=STK_InStock")
    date_field = models.CharField("归日字段", max_length=64, default="FDate")
    status_filter = models.CharField("单据状态过滤", max_length=32, default="C", blank=True, help_text="留空=不限状态；C=已审核")
    window_mode = models.CharField("同步窗口", max_length=20, choices=WindowMode.choices, default=WindowMode.CURRENT_MONTH)
    trailing_days = models.PositiveSmallIntegerField("滚动天数", default=7, help_text="仅『滚动N天』窗口生效")

    # —— 字段映射：逻辑角色 → 金蝶字段名（FieldKey）。留空的角色不查询/不落库。 ——
    fld_fid = models.CharField("单据内码字段", max_length=64, default="FID")
    fld_entry_id = models.CharField("明细内码字段", max_length=64, default="FEntryID")
    fld_bill_no = models.CharField("单据编号字段", max_length=64, default="FBillNo")
    fld_date = models.CharField("业务日期字段", max_length=64, default="FDate")
    fld_status = models.CharField("单据状态字段", max_length=64, default="FDocumentStatus")
    fld_approve_date = models.CharField("审核日期字段", max_length=64, default="FApproveDate", blank=True)
    fld_org_number = models.CharField("组织编码字段", max_length=64, default="FStockOrgId.FNumber", blank=True)
    fld_party_number = models.CharField("客户/供应商编码字段", max_length=64, default="", blank=True, help_text="SAL_OUTSTOCK 表头无客户，可留空或填关联单字段")
    fld_party_name = models.CharField("客户/供应商名称字段", max_length=64, default="", blank=True)
    fld_material_number = models.CharField("物料编码字段", max_length=64, default="FMaterialId.FNumber", blank=True)
    fld_material_name = models.CharField("物料名称字段", max_length=64, default="FMaterialId.FName", blank=True)
    fld_qty = models.CharField("数量字段", max_length=64, default="FRealQty", blank=True)
    fld_unit = models.CharField("单位字段", max_length=64, default="FUnitID.FName", blank=True)
    fld_price = models.CharField("单价字段", max_length=64, default="FPrice", blank=True)
    fld_amount = models.CharField("金额字段", max_length=64, default="FAmount", blank=True)
    fld_currency = models.CharField("币种字段", max_length=64, default="", blank=True)

    is_active = models.BooleanField("启用", default=True)

    class Meta:
        verbose_name = "金蝶表单字段配置"
        verbose_name_plural = "金蝶表单字段配置"
        ordering = ["business_type"]

    def __str__(self):
        return f"{self.get_business_type_display()}（{self.form_id}）"

    def field_map(self):
        """返回 {逻辑角色: 金蝶字段名}，仅含已配置（非空）的角色。"""
        roles = {
            "fid": self.fld_fid, "entry_id": self.fld_entry_id, "bill_no": self.fld_bill_no,
            "date": self.fld_date, "status": self.fld_status, "approve_date": self.fld_approve_date,
            "org_number": self.fld_org_number, "party_number": self.fld_party_number,
            "party_name": self.fld_party_name, "material_number": self.fld_material_number,
            "material_name": self.fld_material_name, "qty": self.fld_qty, "unit": self.fld_unit,
            "price": self.fld_price, "amount": self.fld_amount, "currency": self.fld_currency,
        }
        return {role: key.strip() for role, key in roles.items() if key and key.strip()}


class SyncRun(models.Model):
    """一次同步的留痕，命令据此判断当天是否已成功同步（幂等触发）。"""

    class Integration(models.TextChoices):
        KINGDEE = "KINGDEE", "金蝶"
        DINGTALK = "DINGTALK", "钉钉"

    class Status(models.TextChoices):
        RUNNING = "RUNNING", "进行中"
        SUCCESS = "SUCCESS", "成功"
        FAILED = "FAILED", "失败"

    integration = models.CharField("集成", max_length=10, choices=Integration.choices)
    company = models.ForeignKey(
        "core.Company", verbose_name="公司", null=True, blank=True, on_delete=models.SET_NULL, related_name="sync_runs"
    )
    window_start = models.DateField("窗口起", null=True, blank=True)
    window_end = models.DateField("窗口止", null=True, blank=True)
    status = models.CharField("状态", max_length=10, choices=Status.choices, default=Status.RUNNING)
    rows_upserted = models.PositiveIntegerField("写入行数", default=0)
    rows_disabled = models.PositiveIntegerField("失效行数", default=0)
    message = models.TextField("说明/错误", blank=True, default="")
    started_at = models.DateTimeField("开始时间", auto_now_add=True)
    finished_at = models.DateTimeField("结束时间", null=True, blank=True)

    class Meta:
        verbose_name = "同步记录"
        verbose_name_plural = "同步记录"
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["integration", "company", "-started_at"], name="syncrun_lookup_idx")]

    def __str__(self):
        return f"{self.get_integration_display()} {self.started_at:%Y-%m-%d %H:%M} {self.get_status_display()}"


class KingdeePartyMapping(models.Model):
    """金蝶客户/供应商 ↔ 系统 Customer/Supplier 映射。
    系统侧名称多为简称，故按词/按字模糊匹配；命中多个则落库为候选待人工审核。"""

    class PartyType(models.TextChoices):
        CUSTOMER = "CUSTOMER", "客户"
        SUPPLIER = "SUPPLIER", "供应商"

    class MatchStatus(models.TextChoices):
        AUTO = "AUTO", "自动匹配"
        PENDING = "PENDING", "待人工审核"
        MANUAL = "MANUAL", "人工确定"
        UNMATCHED = "UNMATCHED", "未匹配"

    company = models.ForeignKey(
        "core.Company", verbose_name="公司", on_delete=models.CASCADE, related_name="kingdee_party_mappings"
    )
    party_type = models.CharField("类型", max_length=10, choices=PartyType.choices)
    k3_number = models.CharField("金蝶编码", max_length=64)
    k3_name = models.CharField("金蝶名称", max_length=200)
    customer = models.ForeignKey(
        "core.Customer", verbose_name="系统客户", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    supplier = models.ForeignKey(
        "core.Supplier", verbose_name="系统供应商", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    match_status = models.CharField("匹配状态", max_length=10, choices=MatchStatus.choices, default=MatchStatus.UNMATCHED)
    candidates = models.JSONField("候选项", default=list, blank=True, help_text="模糊命中的多个待选：[{id,name,score}]")
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "金蝶客商映射"
        verbose_name_plural = "金蝶客商映射"
        ordering = ["company", "party_type", "k3_name"]
        constraints = [
            models.UniqueConstraint(fields=["company", "party_type", "k3_number"], name="uniq_party_mapping")
        ]

    def __str__(self):
        return f"{self.get_party_type_display()} {self.k3_name}"

    @property
    def resolved(self):
        return self.customer or self.supplier


class StockTransaction(models.Model):
    """金蝶库存发生单据表头（销售出库 / 采购入库）。唯一性按单据内码 FID。"""

    company = models.ForeignKey(
        "core.Company", verbose_name="公司", on_delete=models.PROTECT, related_name="stock_transactions"
    )
    business_type = models.CharField("业务类型", max_length=20, choices=BusinessType.choices)
    form_id = models.CharField("表单ID", max_length=64)
    fid = models.CharField("单据内码FID", max_length=64)
    bill_no = models.CharField("单据编号", max_length=80, blank=True, default="")
    biz_date = models.DateField("业务日期")
    doc_status = models.CharField("单据状态", max_length=4, blank=True, default="")
    approve_date = models.DateTimeField("审核日期", null=True, blank=True)
    org_number = models.CharField("组织编码", max_length=64, blank=True, default="")
    k3_party_number = models.CharField("客商编码", max_length=64, blank=True, default="")
    k3_party_name = models.CharField("客商名称", max_length=200, blank=True, default="")
    party = models.ForeignKey(
        KingdeePartyMapping, verbose_name="客商映射", null=True, blank=True, on_delete=models.SET_NULL, related_name="transactions"
    )
    currency = models.CharField("币种", max_length=16, blank=True, default="")
    total_amount = models.DecimalField("金额合计", max_digits=20, decimal_places=4, default=0)
    total_quantity = models.DecimalField("数量合计", max_digits=20, decimal_places=6, default=0)
    is_active = models.BooleanField("有效", default=True, help_text="金蝶侧删除/反审核后置为无效，不再计入对比")
    disabled_at = models.DateTimeField("失效时间", null=True, blank=True)
    sync_run = models.ForeignKey(
        SyncRun, verbose_name="来源同步", null=True, blank=True, on_delete=models.SET_NULL, related_name="transactions"
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "库存发生单据"
        verbose_name_plural = "库存发生单据"
        ordering = ["-biz_date", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["company", "form_id", "fid"], name="uniq_stock_txn_fid")
        ]
        indexes = [
            models.Index(fields=["company", "business_type", "biz_date"], name="stocktxn_company_date_idx"),
            models.Index(fields=["company", "business_type", "is_active", "biz_date"], name="stocktxn_active_idx"),
        ]

    def __str__(self):
        return f"{self.get_business_type_display()} {self.bill_no or self.fid}"


class StockTransactionLine(models.Model):
    """库存发生单据的物料明细行。唯一性按明细内码 FEntryID。"""

    transaction = models.ForeignKey(
        StockTransaction, verbose_name="单据", on_delete=models.CASCADE, related_name="lines"
    )
    entry_id = models.CharField("明细内码", max_length=64)
    seq = models.PositiveIntegerField("行号", default=0)
    material_number = models.CharField("物料编码", max_length=80, blank=True, default="")
    material_name = models.CharField("物料名称", max_length=200, blank=True, default="")
    quantity = models.DecimalField("数量", max_digits=20, decimal_places=6, default=0)
    unit = models.CharField("单位", max_length=32, blank=True, default="")
    unit_price = models.DecimalField("单价", max_digits=20, decimal_places=6, default=0)
    amount = models.DecimalField("金额", max_digits=20, decimal_places=4, default=0)

    class Meta:
        verbose_name = "库存发生明细"
        verbose_name_plural = "库存发生明细"
        ordering = ["transaction", "seq"]
        constraints = [
            models.UniqueConstraint(fields=["transaction", "entry_id"], name="uniq_stock_line_entry")
        ]

    def __str__(self):
        return f"{self.material_name or self.material_number} × {self.quantity}"


class DingtalkApp(TimeStampedModel):
    """钉钉企业内部应用凭证。"""

    company = models.OneToOneField(
        "core.Company", verbose_name="公司", on_delete=models.CASCADE, related_name="dingtalk_app"
    )
    name = models.CharField("应用名称", max_length=120, blank=True, default="")
    app_key = models.CharField("AppKey", max_length=128)
    app_secret = models.CharField("AppSecret", max_length=255)
    corp_id = models.CharField("CorpId", max_length=128, blank=True, default="")
    agent_id = models.CharField("AgentId", max_length=64, blank=True, default="")
    is_active = models.BooleanField("启用", default=True)

    class Meta:
        verbose_name = "钉钉应用"
        verbose_name_plural = "钉钉应用"
        ordering = ["company"]

    def __str__(self):
        return f"{self.company} 钉钉应用"


class DingtalkProcessConfig(TimeStampedModel):
    """要同步的 OA 审批模板。本轮聚焦『付款申请』：游离在 K3 之外的费用，用于区分应付/已付。"""

    app = models.ForeignKey(
        DingtalkApp, verbose_name="钉钉应用", on_delete=models.CASCADE, related_name="process_configs"
    )
    process_code = models.CharField("审批模板Code", max_length=128)
    name = models.CharField("模板名称", max_length=120, help_text="如『付款申请』")
    amount_component = models.CharField(
        "金额组件名", max_length=120, blank=True, default="",
        help_text="表单中金额字段的组件名/标题，用于提取付款金额做应付/已付统计",
    )
    lookback_days = models.PositiveSmallIntegerField("回看天数", default=30)
    is_active = models.BooleanField("启用", default=True)

    class Meta:
        verbose_name = "钉钉审批模板"
        verbose_name_plural = "钉钉审批模板"
        ordering = ["app", "name"]
        constraints = [
            models.UniqueConstraint(fields=["app", "process_code"], name="uniq_dingtalk_process")
        ]

    def __str__(self):
        return self.name


class DingtalkApprovalInstance(models.Model):
    """钉钉审批实例（如付款申请）。form_values 保留全部表单值，amount 为提取出的付款金额。"""

    class Result(models.TextChoices):
        AGREE = "agree", "同意"
        REFUSE = "refuse", "拒绝"
        REDIRECT = "redirect", "转交"

    company = models.ForeignKey(
        "core.Company", verbose_name="公司", on_delete=models.CASCADE, related_name="dingtalk_approvals"
    )
    process_code = models.CharField("审批模板Code", max_length=128)
    process_name = models.CharField("模板名称", max_length=120, blank=True, default="")
    process_instance_id = models.CharField("审批实例ID", max_length=128)
    title = models.CharField("标题", max_length=255, blank=True, default="")
    originator_userid = models.CharField("发起人ID", max_length=128, blank=True, default="")
    originator_name = models.CharField("发起人", max_length=120, blank=True, default="")
    dept_name = models.CharField("部门", max_length=120, blank=True, default="")
    status = models.CharField("流程状态", max_length=20, blank=True, default="", help_text="NEW/RUNNING/COMPLETED/TERMINATED")
    result = models.CharField("审批结果", max_length=20, blank=True, default="")
    amount = models.DecimalField("付款金额", max_digits=20, decimal_places=2, null=True, blank=True)
    create_time = models.DateTimeField("发起时间", null=True, blank=True)
    finish_time = models.DateTimeField("完成时间", null=True, blank=True)
    form_values = models.JSONField("表单值", default=dict, blank=True)
    raw = models.JSONField("原始数据", default=dict, blank=True)
    sync_run = models.ForeignKey(
        SyncRun, verbose_name="来源同步", null=True, blank=True, on_delete=models.SET_NULL, related_name="approvals"
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "钉钉审批实例"
        verbose_name_plural = "钉钉审批实例"
        ordering = ["-create_time", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["company", "process_instance_id"], name="uniq_dingtalk_instance")
        ]
        indexes = [
            models.Index(fields=["company", "process_code", "-create_time"], name="dingtalk_lookup_idx"),
        ]

    def __str__(self):
        return self.title or self.process_instance_id
