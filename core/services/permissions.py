from core.models import Customer, PurchaseAssignment, SalesAssignment, Supplier
from core.services.naming import display_name


def is_administrator(user):
    return bool(
        user.is_authenticated
        and (user.is_superuser or user.groups.filter(name="administrator").exists())
    )


def _has_group(user, name):
    return bool(user.is_authenticated and user.groups.filter(name=name).exists())


def can_access_sales(user):
    return bool(
        is_administrator(user)
        or _has_group(user, "sales")
        or SalesAssignment.objects.filter(user=user).exists()
    )


def can_access_purchase(user):
    return bool(
        is_administrator(user)
        or _has_group(user, "purchase")
        or PurchaseAssignment.objects.filter(user=user).exists()
    )


def can_view_comparison(user):
    """采销对比表是全公司口径、不按 owner 过滤的管理层报表，只放管理员和
    report_viewer。不能用 can_view_*_reports：那些对有归属的普通业务员也成立，
    而导入会自动给业务员建归属。"""
    return bool(is_administrator(user) or _has_group(user, "report_viewer"))


def can_view_sales_reports(user):
    return bool(can_access_sales(user) or _has_group(user, "report_viewer"))


def can_view_purchase_reports(user):
    return bool(can_access_purchase(user) or _has_group(user, "report_viewer"))


def _scoped(queryset, company):
    """公司是硬隔离边界：没有当前公司时一条数据都不返回。"""
    if company is None:
        return queryset.none()
    return queryset.filter(company=company)


def customer_queryset_for(user, company):
    queryset = _scoped(Customer.objects.filter(is_active=True), company)
    if is_administrator(user):
        return queryset.order_by("name")
    return queryset.filter(salesassignment__user=user).order_by("name")


def supplier_queryset_for(user, company):
    queryset = _scoped(Supplier.objects.filter(is_active=True), company)
    if is_administrator(user):
        return queryset.order_by("name")
    return queryset.filter(purchaseassignment__user=user).order_by("name")


def customer_options_for(user, company):
    """返回 [(客户, 显示标签, 归属人)]。标签用真实姓名，归属人用于表单自动带出负责人。
    同一客户可能分给多个业务员，所以会出现多个选项，各自带不同归属人。"""
    if company is None:
        return []
    assignments = SalesAssignment.objects.filter(
        customer__is_active=True, customer__company=company
    ).select_related("customer", "user").order_by("customer__name", "user__first_name")
    if not is_administrator(user):
        assignments = assignments.filter(user=user)
    options = [
        (assignment.customer, f"{assignment.customer.name}（{display_name(assignment.user)}）", assignment.user)
        for assignment in assignments
    ]
    if is_administrator(user):
        assigned_ids = {customer.pk for customer, _, _ in options}
        options.extend(
            (customer, f"{customer.name}（未分配）", None)
            for customer in customer_queryset_for(user, company)
            if customer.pk not in assigned_ids
        )
    return options


def supplier_options_for(user, company):
    """返回 [(供应商, 显示标签, 归属人)]，口径与 customer_options_for 一致。"""
    if company is None:
        return []
    assignments = PurchaseAssignment.objects.filter(
        supplier__is_active=True, supplier__company=company
    ).select_related("supplier", "user").order_by("supplier__name", "user__first_name")
    if not is_administrator(user):
        assignments = assignments.filter(user=user)
    options = [
        (assignment.supplier, f"{assignment.supplier.name}（{display_name(assignment.user)}）", assignment.user)
        for assignment in assignments
    ]
    if is_administrator(user):
        assigned_ids = {supplier.pk for supplier, _, _ in options}
        options.extend(
            (supplier, f"{supplier.name}（未分配）", None)
            for supplier in supplier_queryset_for(user, company)
            if supplier.pk not in assigned_ids
        )
    return options
