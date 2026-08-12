# 销售采购轻量日报系统实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在公司内网交付一个同时支持销售出货和采购日报的 Django 单体系统，具备登录、按归属填报、历史数据导入、图表报表、Excel 导出和操作留痕。

**Architecture:** 一个 Django 5 应用承载页面、业务接口、权限和后台管理，SQLite 作为单机数据存储。`core` 仅提供账户、基础资料、归属、汇率、审计和查询范围；`sales` 与 `purchase` 各自拥有模型、导入器、页面和 `/api/**` 接口；`reports` 只读取两个模块已授权的数据。

**Tech Stack:** Python 3.12、Django 5、SQLite（WAL）、HTMX、ECharts、pandas、xlrd、openpyxl、Waitress。

## Global Constraints

- 仅部署在公司内网，使用系统自建账号密码；密码使用 Django 不可逆哈希保存。
- SQLite 必须启用 WAL 和 10 秒写入等待；每日使用 SQLite 在线备份，不复制正在使用的数据库文件。
- 销售与采购分别使用 `sales_shipments`、`purchase_receipts` 数据表和 `/api/sales/**`、`/api/purchase/**` 接口，不接受混合业务明细。
- 内销/国内采购固定 `CNY`，外销/国外采购固定 `USD`；每条记录保存录入日所在月份的汇率快照和折算人民币金额。
- 普通销售人员只能处理本人被分配客户的销售数据；普通采购人员只能处理本人被分配供应商的采购数据；管理员可处理全量数据。
- 销售历史导入必须与 `出货明细(26.7.7）.xls` 对账：4,207 条明细、116 个客户、7 位负责人，且按月和销售类型汇总一致。
- 当前工作目录不是 Git 仓库；实施时不执行提交命令，也不初始化 Git。

---

## 文件结构

```text
dailyReport/
  manage.py
  requirements.txt
  .env.example
  config/
    settings.py
    urls.py
    wsgi.py
  core/
    models.py
    admin.py
    forms.py
    urls.py
    views.py
    services/audit.py
    services/permissions.py
    tests/test_models.py
    tests/test_permissions.py
  sales/
    models.py
    forms.py
    urls.py
    views.py
    services.py
    importers.py
    tests/test_services.py
    tests/test_views.py
    tests/test_importers.py
  purchase/
    models.py
    forms.py
    urls.py
    views.py
    services.py
    importers.py
    tests/test_services.py
    tests/test_views.py
  reports/
    services.py
    urls.py
    views.py
    exporters.py
    tests/test_services.py
    tests/test_exports.py
  templates/
    base.html
    registration/login.html
    sales/shipment_list.html
    sales/shipment_form.html
    purchase/receipt_list.html
    purchase/receipt_form.html
    reports/dashboard.html
  static/js/dashboard.js
  scripts/__init__.py
  scripts/backup_sqlite.py
  scripts/run_waitress.py
  docs/deployment.md
```

### Task 1: 建立 Django 单体项目与 SQLite 运行配置

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `manage.py`
- Create: `config/settings.py`
- Create: `config/urls.py`
- Create: `config/wsgi.py`
- Create: `core/apps.py`
- Create: `core/signals.py`
- Create: `sales/apps.py`
- Create: `purchase/apps.py`
- Create: `reports/apps.py`
- Create: `core/tests/test_settings.py`

**Interfaces:**
- Produces: `config.settings`，为后续四个 Django app 提供 SQLite、模板、静态文件和登录跳转配置。
- Produces: `core.signals.configure_sqlite(sender, connection, **kwargs) -> None`，为 SQLite 连接启用 WAL 和外键约束。

- [ ] **Step 1: 写入会失败的配置测试**

```python
# core/tests/test_settings.py
from django.conf import settings
from django.test import SimpleTestCase


class SettingsTests(SimpleTestCase):
    def test_database_uses_sqlite_with_write_timeout(self):
        database = settings.DATABASES["default"]
        self.assertEqual(database["ENGINE"], "django.db.backends.sqlite3")
        self.assertEqual(database["OPTIONS"]["timeout"], 10)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python manage.py test core.tests.test_settings -v 2`

Expected: FAIL，因为项目文件尚不存在。

- [ ] **Step 3: 创建最小可运行项目和配置**

```text
# requirements.txt
Django==5.1.1
waitress==3.0.0
pandas==2.2.3
xlrd==2.0.1
openpyxl==3.1.5
```

```python
# config/settings.py 中的关键配置
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "data" / "daily_report.sqlite3",
        "OPTIONS": {"timeout": 10},
    }
}
INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "core", "sales", "purchase", "reports",
]
TEMPLATES[0]["DIRS"] = [BASE_DIR / "templates"]
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
```

```python
# core/signals.py
from django.db.backends.signals import connection_created
from django.dispatch import receiver


@receiver(connection_created)
def configure_sqlite(sender, connection, **kwargs):
    if connection.vendor != "sqlite":
        return
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=10000")
```

在 `core/apps.py` 的 `ready()` 中导入 `core.signals`，并在 `config/urls.py` 挂载 Django 登录页面和后续 app 路由。

- [ ] **Step 4: 运行测试确认通过并执行迁移检查**

Run: `python manage.py test core.tests.test_settings -v 2`

Expected: PASS。

Run: `python manage.py check`

Expected: `System check identified no issues`。

- [ ] **Step 5: 记录变更**

记录本任务创建的文件和测试结果；当前目录没有 Git 仓库，不执行提交命令。

### Task 2: 实现基础资料、角色、归属、汇率与审计

**Files:**
- Create: `core/models.py`
- Create: `core/admin.py`
- Create: `core/forms.py`
- Create: `core/services/audit.py`
- Create: `core/services/permissions.py`
- Create: `core/tests/test_models.py`
- Create: `core/tests/test_permissions.py`

**Interfaces:**
- Produces: `Customer`、`Supplier`、`SalesAssignment`、`PurchaseAssignment`、`ExchangeRate`、`OperationLog`。
- Produces: `customer_queryset_for(user)` 与 `supplier_queryset_for(user)`，返回当前用户可选的往来单位 QuerySet。
- Produces: `record_audit(*, actor, instance, action, before, after) -> OperationLog`。

- [ ] **Step 1: 写入归属范围和汇率验证测试**

```python
# core/tests/test_models.py
from datetime import date
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from core.models import Customer, ExchangeRate, SalesAssignment


class ExchangeRateTests(TestCase):
    def test_rate_month_must_be_first_day(self):
        rate = ExchangeRate(month=date(2026, 8, 10), usd_to_cny="6.8067")
        with self.assertRaises(ValidationError):
            rate.full_clean()


class AssignmentTests(TestCase):
    def test_customer_assignment_is_unique_per_user_and_customer(self):
        user = User.objects.create_user("sales-a")
        customer = Customer.objects.create(name="客户 A")
        SalesAssignment.objects.create(user=user, customer=customer)
        duplicate = SalesAssignment(user=user, customer=customer)
        with self.assertRaises(ValidationError):
            duplicate.full_clean()
```

```python
# core/tests/test_permissions.py
from django.contrib.auth.models import Group, User
from django.test import TestCase
from core.models import Customer, SalesAssignment
from core.services.permissions import customer_queryset_for


class CustomerScopeTests(TestCase):
    def test_sales_user_only_receives_assigned_customers(self):
        sales = User.objects.create_user("sales-a")
        sales_group, _ = Group.objects.get_or_create(name="sales")
        sales.groups.add(sales_group)
        assigned = Customer.objects.create(name="客户 A")
        Customer.objects.create(name="客户 B")
        SalesAssignment.objects.create(user=sales, customer=assigned)
        self.assertEqual(list(customer_queryset_for(sales)), [assigned])
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python manage.py test core.tests -v 2`

Expected: FAIL，提示 `core.models` 和服务尚未定义。

- [ ] **Step 3: 实现模型、范围服务和审计服务**

```python
# core/models.py 中的核心定义
class Customer(models.Model):
    name = models.CharField(max_length=120, unique=True)


class Supplier(models.Model):
    name = models.CharField(max_length=120, unique=True)


class SalesAssignment(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "customer"], name="unique_sales_assignment")]


class PurchaseAssignment(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "supplier"], name="unique_purchase_assignment")]


class ExchangeRate(models.Model):
    month = models.DateField(unique=True)
    usd_to_cny = models.DecimalField(max_digits=10, decimal_places=4)

    def clean(self):
        if self.month.day != 1:
            raise ValidationError("汇率月份必须保存为当月 1 日")
```

```python
# core/services/permissions.py
def is_administrator(user):
    return user.is_superuser or user.groups.filter(name="administrator").exists()


def customer_queryset_for(user):
    if is_administrator(user):
        return Customer.objects.order_by("name")
    return Customer.objects.filter(salesassignment__user=user).order_by("name")


def supplier_queryset_for(user):
    if is_administrator(user):
        return Supplier.objects.order_by("name")
    return Supplier.objects.filter(purchaseassignment__user=user).order_by("name")


```

`OperationLog` 保存操作人、动作、模型标签、对象主键、修改前 JSON、修改后 JSON 和时间；`record_audit` 使用 `model_to_dict` 写入 JSON。将所有基础资料模型注册到 Django admin，并创建 `administrator`、`sales`、`purchase`、`report_viewer` 四个 Group 的数据迁移。

- [ ] **Step 4: 创建并运行迁移与测试**

Run: `python manage.py makemigrations core && python manage.py migrate`

Expected: `core` 迁移成功应用。

Run: `python manage.py test core.tests -v 2`

Expected: PASS。

- [ ] **Step 5: 记录变更**

记录 `core` 模型、权限测试和迁移结果；当前目录没有 Git 仓库，不执行提交命令。

### Task 3: 实现销售日报、权限和汇率快照

**Files:**
- Create: `sales/models.py`
- Create: `sales/forms.py`
- Create: `sales/services.py`
- Create: `sales/views.py`
- Create: `sales/urls.py`
- Create: `sales/admin.py`
- Create: `sales/tests/test_services.py`
- Create: `sales/tests/test_views.py`
- Create: `templates/sales/shipment_list.html`
- Create: `templates/sales/shipment_form.html`

**Interfaces:**
- Consumes: `Customer`、`SalesAssignment`、`ExchangeRate`、`record_audit`、`customer_queryset_for`。
- Produces: `SalesShipment`、`create_sales_shipment(*, actor, data)`、`sales_queryset_for(user)`。
- Produces: `GET|POST /sales/shipments/` 和 `GET|POST /api/sales/shipments/`。

- [ ] **Step 1: 写入销售类型、汇率和越权测试**

```python
# sales/tests/test_services.py
from datetime import date
from django.contrib.auth.models import User
from django.test import TestCase
from core.models import Customer, ExchangeRate, SalesAssignment
from sales.services import create_sales_shipment


class SalesShipmentServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("sales-a")
        self.customer = Customer.objects.create(name="客户 A")
        SalesAssignment.objects.create(user=self.user, customer=self.customer)
        ExchangeRate.objects.create(month=date(2026, 8, 1), usd_to_cny="6.8067")

    def test_export_sale_uses_usd_and_month_rate_snapshot(self):
        shipment = create_sales_shipment(actor=self.user, data={
            "customer": self.customer, "sale_type": "EXPORT", "shipment_date": date(2026, 8, 10),
            "quantity": 20, "original_amount": "100.00",
        })
        self.assertEqual(shipment.currency, "USD")
        self.assertEqual(str(shipment.exchange_rate), "6.8067")
        self.assertEqual(str(shipment.amount_cny), "680.67")
```

```python
# sales/tests/test_views.py
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from core.models import Customer, SalesAssignment


class SalesViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("sales-a")
        self.assigned = Customer.objects.create(name="客户 A")
        SalesAssignment.objects.create(user=self.user, customer=self.assigned)

    def test_unassigned_customer_is_rejected(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("sales:shipment_create"), {
            "customer": Customer.objects.create(name="未分配客户").pk,
            "sale_type": "DOMESTIC", "shipment_date": "2026-08-10",
            "quantity": 1, "original_amount": "10.00",
        })
        self.assertEqual(response.status_code, 400)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python manage.py test sales.tests -v 2`

Expected: FAIL，提示 `sales` 模块和 `create_sales_shipment` 尚未定义。

- [ ] **Step 3: 实现销售模型、服务、表单和页面**

```python
# sales/models.py
class SalesShipment(models.Model):
    class SaleType(models.TextChoices):
        DOMESTIC = "DOMESTIC", "内销"
        EXPORT = "EXPORT", "外销"

    customer = models.ForeignKey("core.Customer", on_delete=models.PROTECT)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    sale_type = models.CharField(max_length=10, choices=SaleType.choices)
    shipment_date = models.DateField()
    quantity = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, editable=False)
    original_amount = models.DecimalField(max_digits=14, decimal_places=2)
    exchange_rate = models.DecimalField(max_digits=10, decimal_places=4)
    amount_cny = models.DecimalField(max_digits=16, decimal_places=2)
    source = models.CharField(max_length=20, default="MANUAL")
    source_file = models.CharField(max_length=255, blank=True, default="")
    import_batch = models.UUIDField(null=True, blank=True)
    source_row = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "sales_shipments"
```

```python
# sales/services.py
from decimal import Decimal
from core.models import ExchangeRate, SalesAssignment
from core.services.audit import record_audit
from core.services.permissions import is_administrator
from sales.models import SalesShipment


def sales_queryset_for(user):
    queryset = SalesShipment.objects.select_related("customer", "owner")
    return queryset if is_administrator(user) else queryset.filter(owner=user)


def create_sales_shipment(*, actor, data):
    if not SalesAssignment.objects.filter(user=actor, customer=data["customer"]).exists():
        raise PermissionError("客户未分配给当前销售人员")
    currency = "CNY" if data["sale_type"] == "DOMESTIC" else "USD"
    applied_rate = Decimal("1")
    if currency == "USD":
        applied_rate = ExchangeRate.objects.get(month=data["shipment_date"].replace(day=1)).usd_to_cny
    amount = Decimal(data["original_amount"])
    shipment = SalesShipment.objects.create(
        owner=actor, currency=currency, exchange_rate=applied_rate,
        amount_cny=amount * applied_rate, **data,
    )
    record_audit(actor=actor, instance=shipment, action="CREATE", before={}, after={"amount_cny": str(shipment.amount_cny)})
    return shipment
```

表单只暴露客户、销售类型、日期、数量和原币金额；视图从 `customer_queryset_for(request.user)` 注入客户选项。更新和删除必须以 `owner=request.user` 过滤，管理员才可跨负责人操作，并在每次动作后写入 `OperationLog`。使用 HTMX 在日期或销售类型变化时返回币种和预估汇率。

- [ ] **Step 4: 迁移并运行销售测试**

Run: `python manage.py makemigrations sales && python manage.py migrate`

Expected: 创建 `sales_shipments`。

Run: `python manage.py test sales.tests -v 2`

Expected: PASS。

- [ ] **Step 5: 记录变更**

记录销售日报录入、越权拦截和汇率快照测试结果；当前目录没有 Git 仓库，不执行提交命令。

### Task 4: 实现采购日报并保持与销售的独立边界

**Files:**
- Create: `purchase/models.py`
- Create: `purchase/forms.py`
- Create: `purchase/services.py`
- Create: `purchase/views.py`
- Create: `purchase/urls.py`
- Create: `purchase/admin.py`
- Create: `purchase/tests/test_services.py`
- Create: `purchase/tests/test_views.py`
- Create: `templates/purchase/receipt_list.html`
- Create: `templates/purchase/receipt_form.html`

**Interfaces:**
- Consumes: `Supplier`、`PurchaseAssignment`、`ExchangeRate`、`record_audit`、`supplier_queryset_for`。
- Produces: `PurchaseReceipt`、`create_purchase_receipt(*, actor, data)`、`purchase_queryset_for(user)`。
- Produces: `GET|POST /purchase/receipts/` 和 `GET|POST /api/purchase/receipts/`。

- [ ] **Step 1: 写入采购币种、归属和数据串域测试**

```python
# purchase/tests/test_services.py
from datetime import date
from django.contrib.auth.models import User
from django.test import TestCase
from core.models import ExchangeRate, Supplier, PurchaseAssignment
from purchase.services import create_purchase_receipt


class PurchaseReceiptServiceTests(TestCase):
    def test_domestic_purchase_uses_cny_without_foreign_rate(self):
        user = User.objects.create_user("buyer-a")
        supplier = Supplier.objects.create(name="供应商 A")
        PurchaseAssignment.objects.create(user=user, supplier=supplier)
        ExchangeRate.objects.create(month=date(2026, 8, 1), usd_to_cny="6.8067")
        receipt = create_purchase_receipt(actor=user, data={
            "supplier": supplier, "purchase_type": "DOMESTIC", "purchase_date": date(2026, 8, 10),
            "quantity": 5, "original_amount": "88.00",
        })
        self.assertEqual(receipt.currency, "CNY")
        self.assertEqual(str(receipt.amount_cny), "88.00")
```

```python
# purchase/tests/test_views.py
from django.test import TestCase
from django.urls import resolve


class PurchaseRouteTests(TestCase):
    def test_purchase_api_does_not_resolve_to_sales_view(self):
        match = resolve("/api/purchase/receipts/")
        self.assertEqual(match.namespace, "purchase")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python manage.py test purchase.tests -v 2`

Expected: FAIL，提示 `purchase` 模块未定义。

- [ ] **Step 3: 实现采购模型、服务、表单和页面**

```python
# purchase/models.py
class PurchaseReceipt(models.Model):
    class PurchaseType(models.TextChoices):
        DOMESTIC = "DOMESTIC", "国内采购"
        FOREIGN = "FOREIGN", "国外采购"

    supplier = models.ForeignKey("core.Supplier", on_delete=models.PROTECT)
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    purchase_type = models.CharField(max_length=10, choices=PurchaseType.choices)
    purchase_date = models.DateField()
    quantity = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, editable=False)
    original_amount = models.DecimalField(max_digits=14, decimal_places=2)
    exchange_rate = models.DecimalField(max_digits=10, decimal_places=4)
    amount_cny = models.DecimalField(max_digits=16, decimal_places=2)
    source = models.CharField(max_length=20, default="MANUAL")
    source_file = models.CharField(max_length=255, blank=True, default="")
    import_batch = models.UUIDField(null=True, blank=True)
    source_row = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = "purchase_receipts"
```

```python
# purchase/services.py
from core.services.permissions import is_administrator


def purchase_queryset_for(user):
    queryset = PurchaseReceipt.objects.select_related("supplier", "buyer")
    return queryset if is_administrator(user) else queryset.filter(buyer=user)


def create_purchase_receipt(*, actor, data):
    if not PurchaseAssignment.objects.filter(user=actor, supplier=data["supplier"]).exists():
        raise PermissionError("供应商未分配给当前采购人员")
    currency = "CNY" if data["purchase_type"] == "DOMESTIC" else "USD"
    applied_rate = Decimal("1")
    if currency == "USD":
        applied_rate = ExchangeRate.objects.get(month=data["purchase_date"].replace(day=1)).usd_to_cny
    amount = Decimal(data["original_amount"])
    receipt = PurchaseReceipt.objects.create(
        buyer=actor, currency=currency, exchange_rate=applied_rate,
        amount_cny=amount * applied_rate, **data,
    )
    record_audit(actor=actor, instance=receipt, action="CREATE", before={}, after={"amount_cny": str(receipt.amount_cny)})
    return receipt
```

采购页面只处理供应商、采购类型、日期、数量和原币金额；不得从 `sales` app 导入任何模型、表单、视图或 URL。对外采购选择时强制 `USD`，对内采购选择时强制 `CNY`。

- [ ] **Step 4: 迁移并运行采购测试**

Run: `python manage.py makemigrations purchase && python manage.py migrate`

Expected: 创建 `purchase_receipts`，且不修改 `sales_shipments`。

Run: `python manage.py test purchase.tests -v 2`

Expected: PASS。

- [ ] **Step 5: 记录变更**

记录采购日报、供应商范围和独立路由测试结果；当前目录没有 Git 仓库，不执行提交命令。

### Task 5: 实现销售和采购的导入预览、校验与正式写入

**Files:**
- Create: `sales/importers.py`
- Create: `sales/tests/test_importers.py`
- Create: `purchase/importers.py`
- Create: `purchase/tests/test_importers.py`
- Modify: `sales/views.py`
- Modify: `sales/urls.py`
- Modify: `purchase/views.py`
- Modify: `purchase/urls.py`

**Interfaces:**
- Consumes: 销售列 `客户名称`、`业务跟单`、`销售类型`、`出货日期`、`数量`、`金额`；采购的同结构列映射。
- Produces: `preview_sales_import(path) -> ImportPreview`、`commit_sales_import(preview, actor) -> int`。
- Produces: `preview_purchase_import(path) -> ImportPreview`、`commit_purchase_import(preview, actor) -> int`。
- Produces: `write_sales_rows(rows, *, actor, source) -> int` 与 `write_purchase_rows(rows, *, actor, source) -> int`，在事务内调用各自领域服务并返回写入行数。
- Produces: `POST /api/sales/imports/preview/`、`POST /api/sales/imports/commit/`、`POST /api/purchase/imports/preview/`、`POST /api/purchase/imports/commit/`。

- [ ] **Step 1: 写入销售源表映射与不自动去重测试**

```python
# sales/tests/test_importers.py
from pathlib import Path
from django.test import SimpleTestCase
from sales.importers import validate_sales_dataframe


class SalesImporterTests(SimpleTestCase):
    def test_identical_business_rows_are_retained(self):
        rows = [
            {"客户名称": "客户 A", "业务跟单": "张三", "销售类型": "内销", "出货日期": "2026-08-10", "数量": 1, "金额": 10},
            {"客户名称": "客户 A", "业务跟单": "张三", "销售类型": "内销", "出货日期": "2026-08-10", "数量": 1, "金额": 10},
        ]
        preview = validate_sales_dataframe(rows)
        self.assertEqual(preview.valid_row_count, 2)
        self.assertEqual(preview.error_rows, [])
```

```python
# purchase/tests/test_importers.py
from django.test import SimpleTestCase
from purchase.importers import validate_purchase_dataframe


class PurchaseImporterTests(SimpleTestCase):
    def test_missing_supplier_is_reported_with_source_row(self):
        preview = validate_purchase_dataframe([
            {"供应商": "", "采购员": "李四", "采购类型": "国内采购", "采购日期": "2026-08-10", "数量": 1, "金额": 10}
        ])
        self.assertEqual(preview.error_rows[0]["row_number"], 2)
        self.assertEqual(preview.error_rows[0]["field"], "供应商")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python manage.py test sales.tests.test_importers purchase.tests.test_importers -v 2`

Expected: FAIL，提示导入器尚未定义。

- [ ] **Step 3: 实现导入器与管理员导入页面**

```python
# sales/importers.py 的字段映射和校验骨架
from dataclasses import dataclass
import pandas as pd
from django.db import transaction
from core.services.permissions import is_administrator


@dataclass(frozen=True)
class ImportPreview:
    valid_row_count: int
    error_rows: list[dict]
    rows: list[dict]


SALES_COLUMNS = {
    "客户名称": "customer_name", "业务跟单": "owner_name", "销售类型": "sale_type",
    "出货日期": "shipment_date", "数量": "quantity", "金额": "original_amount",
}


def validate_sales_dataframe(rows):
    errors = []
    valid_rows = []
    for row_number, row in enumerate(rows, start=2):
        for source_column in SALES_COLUMNS:
            if row.get(source_column) in (None, ""):
                errors.append({"row_number": row_number, "field": source_column, "message": "不能为空"})
        if not any(error["row_number"] == row_number for error in errors):
            valid_rows.append(row)
    return ImportPreview(valid_row_count=len(valid_rows), error_rows=errors, rows=valid_rows)


def preview_sales_import(path):
    dataframe = pd.read_excel(path, engine="xlrd")
    return validate_sales_dataframe(dataframe.to_dict("records"))


def commit_sales_import(preview, actor):
    if not is_administrator(actor):
        raise PermissionError("只有管理员可以正式导入")
    with transaction.atomic():
        return write_sales_rows(preview.rows, actor=actor, source="HISTORY_IMPORT")
```

导入预览必须在数据库写入前显示有效行数、错误行号和字段错误。正式导入仅允许管理员执行，在单一 `transaction.atomic()` 中写入，逐行保存来源文件名、导入批次 UUID、来源行号和 `HISTORY_IMPORT` 来源。销售正式导入后校验记录数等于 4,207，并生成按月、销售类型、数量和金额的对账结果。采购使用独立 `PURCHASE_COLUMNS`、预览和写入服务。

- [ ] **Step 4: 运行导入测试和销售对账测试**

Run: `python manage.py test sales.tests.test_importers purchase.tests.test_importers -v 2`

Expected: PASS。

Run: `python manage.py test sales.tests -v 2`

Expected: PASS，且同业务字段的两个来源行均被保留。

- [ ] **Step 5: 记录变更**

记录导入预览、错误行、事务写入和销售对账的测试结果；当前目录没有 Git 仓库，不执行提交命令。

### Task 6: 实现分域报表、图表数据和 Excel 导出

**Files:**
- Create: `reports/services.py`
- Create: `reports/exporters.py`
- Create: `reports/views.py`
- Create: `reports/urls.py`
- Create: `reports/tests/test_services.py`
- Create: `reports/tests/test_exports.py`
- Create: `templates/reports/dashboard.html`
- Create: `static/js/dashboard.js`
- Modify: `config/urls.py`

**Interfaces:**
- Consumes: `sales_queryset_for(user)` 和 `purchase_queryset_for(user)`，以及日期、人员、往来单位和业务类型筛选参数。
- Produces: `sales_dashboard(user, filters) -> dict`、`purchase_dashboard(user, filters) -> dict`。
- Produces: `GET /reports/sales/`、`GET /reports/purchase/`、`GET /api/reports/sales/`、`GET /api/reports/purchase/` 和两个 `/export/` 路由。

- [ ] **Step 1: 写入报表口径和导出列测试**

```python
# reports/tests/test_services.py
from datetime import date
from decimal import Decimal
from django.contrib.auth.models import User
from django.test import TestCase
from core.models import Customer
from sales.models import SalesShipment
from reports.services import sales_dashboard


class SalesDashboardTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", password="pw")
        customer = Customer.objects.create(name="客户 A")
        SalesShipment.objects.create(
            customer=customer, owner=self.admin, sale_type="DOMESTIC", shipment_date=date(2026, 8, 10),
            quantity=1, currency="CNY", original_amount="88.00", exchange_rate="1.0000", amount_cny="88.00",
        )
        SalesShipment.objects.create(
            customer=customer, owner=self.admin, sale_type="EXPORT", shipment_date=date(2026, 8, 10),
            quantity=1, currency="USD", original_amount="100.00", exchange_rate="6.8067", amount_cny="680.67",
        )

    def test_summary_keeps_cny_usd_and_converted_total_separate(self):
        dashboard = sales_dashboard(self.admin, {"start": "2026-08-01", "end": "2026-08-31"})
        self.assertEqual(dashboard["summary"]["cny_amount"], Decimal("88.00"))
        self.assertEqual(dashboard["summary"]["usd_amount"], Decimal("100.00"))
        self.assertEqual(dashboard["summary"]["amount_cny"], Decimal("768.67"))
```

```python
# reports/tests/test_exports.py
from django.contrib.auth.models import User
from django.test import TestCase
from core.models import Customer
from sales.models import SalesShipment
from reports.exporters import sales_export_rows


class SalesExportTests(TestCase):
    def setUp(self):
        user = User.objects.create_user("sales-a")
        customer = Customer.objects.create(name="客户 A")
        SalesShipment.objects.create(
            customer=customer, owner=user, sale_type="DOMESTIC", shipment_date="2026-08-10",
            quantity=1, currency="CNY", original_amount="88.00", exchange_rate="1.0000", amount_cny="88.00",
        )
        self.shipments = SalesShipment.objects.all()

    def test_export_headers_include_original_and_converted_amounts(self):
        headers, rows = sales_export_rows(self.shipments)
        self.assertEqual(headers, ["出货日期", "客户", "负责人", "销售类型", "数量", "币种", "原币金额", "汇率快照", "折算人民币金额"])
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python manage.py test reports.tests -v 2`

Expected: FAIL，提示报表服务和导出器尚未定义。

- [ ] **Step 3: 实现授权聚合、图表 JSON 和导出器**

```python
# reports/services.py 中的金额聚合模式
from decimal import Decimal
from django.db.models import DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce, TruncDay, TruncMonth
from sales.services import sales_queryset_for
from purchase.services import purchase_queryset_for


def apply_sales_filters(queryset, filters):
    if filters.get("start"):
        queryset = queryset.filter(shipment_date__gte=filters["start"])
    if filters.get("end"):
        queryset = queryset.filter(shipment_date__lte=filters["end"])
    if filters.get("owner_id"):
        queryset = queryset.filter(owner_id=filters["owner_id"])
    if filters.get("customer_id"):
        queryset = queryset.filter(customer_id=filters["customer_id"])
    if filters.get("sale_type"):
        queryset = queryset.filter(sale_type=filters["sale_type"])
    return queryset


def trend_by_day(queryset, date_field):
    return list(queryset.values(day=TruncDay(date_field)).annotate(amount_cny=Sum("amount_cny"), quantity=Sum("quantity")).order_by("day"))


def trend_by_month(queryset, date_field):
    return list(queryset.values(month=TruncMonth(date_field)).annotate(amount_cny=Sum("amount_cny"), quantity=Sum("quantity")).order_by("month"))


def share_by_field(queryset, field):
    return list(queryset.values(field).annotate(amount_cny=Sum("amount_cny"), quantity=Sum("quantity")).order_by("-amount_cny"))


def rank_by_field(queryset, field):
    return list(queryset.values(field).annotate(amount_cny=Sum("amount_cny"), quantity=Sum("quantity")).order_by("-amount_cny")[:10])


def summary_for(queryset):
    return queryset.aggregate(
        quantity=Coalesce(Sum("quantity"), 0),
        cny_amount=Coalesce(Sum("original_amount", filter=Q(currency="CNY")), Decimal("0")),
        usd_amount=Coalesce(Sum("original_amount", filter=Q(currency="USD")), Decimal("0")),
        amount_cny=Coalesce(Sum("amount_cny"), Decimal("0")),
    )


def sales_dashboard(user, filters):
    queryset = apply_sales_filters(sales_queryset_for(user), filters)
    return {
        "summary": summary_for(queryset),
        "daily_trend": trend_by_day(queryset, "shipment_date"),
        "monthly_trend": trend_by_month(queryset, "shipment_date"),
        "type_share": share_by_field(queryset, "sale_type"),
        "owner_rank": rank_by_field(queryset, "owner__username"),
        "customer_rank": rank_by_field(queryset, "customer__name"),
    }


def apply_purchase_filters(queryset, filters):
    if filters.get("start"):
        queryset = queryset.filter(purchase_date__gte=filters["start"])
    if filters.get("end"):
        queryset = queryset.filter(purchase_date__lte=filters["end"])
    if filters.get("buyer_id"):
        queryset = queryset.filter(buyer_id=filters["buyer_id"])
    if filters.get("supplier_id"):
        queryset = queryset.filter(supplier_id=filters["supplier_id"])
    if filters.get("purchase_type"):
        queryset = queryset.filter(purchase_type=filters["purchase_type"])
    return queryset


def purchase_dashboard(user, filters):
    queryset = apply_purchase_filters(purchase_queryset_for(user), filters)
    return {
        "summary": summary_for(queryset),
        "daily_trend": trend_by_day(queryset, "purchase_date"),
        "monthly_trend": trend_by_month(queryset, "purchase_date"),
        "type_share": share_by_field(queryset, "purchase_type"),
        "owner_rank": rank_by_field(queryset, "buyer__username"),
        "supplier_rank": rank_by_field(queryset, "supplier__name"),
    }
```

`purchase_dashboard` 必须只查询 `PurchaseReceipt`，字段映射为 `purchase_date`、`purchase_type`、`buyer__username` 和 `supplier__name`。模板使用 `json_script` 输出服务返回的数据，`static/js/dashboard.js` 用 ECharts 绘制趋势、结构和排行。导出器使用 `openpyxl` 创建 `.xlsx`，并使用当前筛选后的授权 QuerySet。

- [ ] **Step 4: 运行报表和导出测试**

Run: `python manage.py test reports.tests -v 2`

Expected: PASS。

Run: `python manage.py test -v 2`

Expected: 全部测试 PASS。

- [ ] **Step 5: 记录变更**

记录销售和采购的日报、累计、趋势、结构、排行与 Excel 导出测试结果；当前目录没有 Git 仓库，不执行提交命令。

### Task 7: 完成部署、在线备份和上线验收

**Files:**
- Create: `scripts/run_waitress.py`
- Create: `scripts/backup_sqlite.py`
- Create: `docs/deployment.md`
- Create: `core/tests/test_backup.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: `python scripts/run_waitress.py`，在 `0.0.0.0:8000` 提供内网服务。
- Produces: `python scripts/backup_sqlite.py --target <directory>`，生成一致的 SQLite 在线备份文件。

- [ ] **Step 1: 写入备份文件和环境变量测试**

```python
# core/tests/test_backup.py
from pathlib import Path
from tempfile import TemporaryDirectory
from django.test import SimpleTestCase
from scripts.backup_sqlite import backup_database


class BackupTests(SimpleTestCase):
    def test_backup_database_creates_sqlite_file(self):
        with TemporaryDirectory() as directory:
            output = backup_database(Path(directory))
            self.assertTrue(output.exists())
            self.assertEqual(output.suffix, ".sqlite3")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python manage.py test core.tests.test_backup -v 2`

Expected: FAIL，提示 `scripts.backup_sqlite` 尚未定义。

- [ ] **Step 3: 实现 Waitress 启动和 SQLite 在线备份**

```python
# scripts/backup_sqlite.py
import sqlite3
from datetime import datetime
from pathlib import Path
from django.conf import settings


def backup_database(target: Path) -> Path:
    target.mkdir(parents=True, exist_ok=True)
    output = target / f"daily-report-{datetime.now():%Y%m%d-%H%M%S}.sqlite3"
    source = sqlite3.connect(settings.DATABASES["default"]["NAME"])
    destination = sqlite3.connect(output)
    with destination:
        source.backup(destination)
    destination.close()
    source.close()
    return output
```

```python
# scripts/run_waitress.py
import os
from waitress import serve

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
from config.wsgi import application

serve(application, host="0.0.0.0", port=8000, threads=8)
```

`docs/deployment.md` 必须包含：创建 Python 虚拟环境、安装 `requirements.txt`、执行迁移、创建管理员、以 Windows 服务或 Linux 进程守护启动、每日计划任务运行在线备份、恢复前停服务并保留原数据库副本的命令。`.env.example` 包含 `DJANGO_SECRET_KEY`、`DJANGO_DEBUG=False`、`DJANGO_ALLOWED_HOSTS` 和 `BACKUP_DIRECTORY`。

- [ ] **Step 4: 运行备份、全量测试和人工验收**

Run: `python manage.py test core.tests.test_backup -v 2`

Expected: PASS。

Run: `python manage.py test -v 2`

Expected: 全部测试 PASS。

Run: `python manage.py check --deploy`

Expected: 除由内网部署配置决定的 HTTPS 提示外，无 ERROR。

人工验收：以销售人员、采购人员、管理员和报表查看者四种账号登录；验证各自数据范围；分别录入 CNY 与 USD；导入销售历史表并对账 4,207 条；打开销售和采购图表；导出筛选结果；执行一次在线备份并确认可打开数据库文件。

- [ ] **Step 5: 记录发布结果**

记录服务器地址、备份目录、管理员交接人、销售导入对账结果和采购历史数据导入结果；当前目录没有 Git 仓库，不执行提交命令。

## 计划自检

- 规格覆盖：Task 1-2 覆盖登录、基础资料、权限、汇率和审计；Task 3 覆盖销售；Task 4 覆盖采购及独立边界；Task 5 覆盖导入与销售历史对账；Task 6 覆盖报表、图表和导出；Task 7 覆盖内网部署、WAL、备份和验收。
- 内容完整性检查：本计划中的功能边界均已明确；采购字段按已确认的日报结构实施，采购历史文件在 Task 5 的同类导入流程中提供。
- 接口一致性：销售统一使用 `SalesShipment`、`create_sales_shipment` 和 `/api/sales/**`；采购统一使用 `PurchaseReceipt`、`create_purchase_receipt` 和 `/api/purchase/**`；两个模块不共享业务模型或写入接口。
