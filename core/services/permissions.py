from core.models import Customer, PurchaseAssignment, SalesAssignment, Supplier


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


def can_view_sales_reports(user):
    return bool(can_access_sales(user) or _has_group(user, "report_viewer"))


def can_view_purchase_reports(user):
    return bool(can_access_purchase(user) or _has_group(user, "report_viewer"))


def customer_queryset_for(user):
    if is_administrator(user):
        return Customer.objects.filter(is_active=True).order_by("name")
    return Customer.objects.filter(
        is_active=True, salesassignment__user=user
    ).order_by("name")


def supplier_queryset_for(user):
    if is_administrator(user):
        return Supplier.objects.filter(is_active=True).order_by("name")
    return Supplier.objects.filter(
        is_active=True, purchaseassignment__user=user
    ).order_by("name")


def customer_options_for(user):
    assignments = SalesAssignment.objects.filter(customer__is_active=True).select_related("customer", "user")
    if not is_administrator(user):
        assignments = assignments.filter(user=user)
    options = [(assignment.customer, f"{assignment.customer.name}（{assignment.user.username}）") for assignment in assignments]
    if is_administrator(user):
        assigned_ids = {customer.pk for customer, _ in options}
        options.extend((customer, f"{customer.name}（未分配）") for customer in customer_queryset_for(user) if customer.pk not in assigned_ids)
    return options


def supplier_options_for(user):
    assignments = PurchaseAssignment.objects.filter(supplier__is_active=True).select_related("supplier", "user")
    if not is_administrator(user):
        assignments = assignments.filter(user=user)
    options = [(assignment.supplier, f"{assignment.supplier.name}（{assignment.user.username}）") for assignment in assignments]
    if is_administrator(user):
        assigned_ids = {supplier.pk for supplier, _ in options}
        options.extend((supplier, f"{supplier.name}（未分配）") for supplier in supplier_queryset_for(user) if supplier.pk not in assigned_ids)
    return options
