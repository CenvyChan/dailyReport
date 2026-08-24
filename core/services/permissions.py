from core.models import Customer, PurchaseAssignment, SalesAssignment, Supplier
from core.services.naming import display_name


def is_administrator(user):
    return bool(
        user.is_authenticated
        and (user.is_superuser or user.groups.filter(name="administrator").exists())
    )


def _has_group(user, name):
    return bool(user.is_authenticated and user.groups.filter(name=name).exists())


def is_read_only(user):
    """report_viewer 是纯查看角色：能看两条业务线的全部日报和报表，但不能增删改。

    判断放在这里而不是散在各视图：只读是角色属性，不是某个页面的规则。
    管理员即使也在 report_viewer 组里也不受限。
    """
    if is_administrator(user):
        return False
    return _has_group(user, "report_viewer") and not (
        _has_group(user, "sales") or _has_group(user, "purchase")
    )


def can_access_sales(user, company=None):
    """能否进入销售模块。

    传了 company 就要求绑定属于该公司：SalesAssignment 没有 company 字段，
    公司归属靠 customer.company 间接确定，不加这层限制的话 A 公司的客户绑定
    会让这个人在 B 公司也拿到销售权限，等于绕过公司隔离。
    """
    if is_administrator(user) or _has_group(user, "sales") or _has_group(user, "report_viewer"):
        return True
    assignments = SalesAssignment.objects.filter(user=user)
    if company is not None:
        assignments = assignments.filter(customer__company=company)
    return assignments.exists()


def can_access_purchase(user, company=None):
    if is_administrator(user) or _has_group(user, "purchase") or _has_group(user, "report_viewer"):
        return True
    assignments = PurchaseAssignment.objects.filter(user=user)
    if company is not None:
        assignments = assignments.filter(supplier__company=company)
    return assignments.exists()


def can_view_comparison(user, company=None):
    """采销对比表现在与明细同口径：能进任一业务线的人都能看。

    此前只放管理员和 report_viewer，理由是导入会自动给业务员建归属、用
    can_view_*_reports 判断会让业务员蒙到全公司汇总。现在明细本身就是全公司
    可见，对比表再挡着已无意义。

    口径必须和 can_access_* 一致（含「只有绑定、不在任何组」这种人），否则会
    出现能看明细却看不了汇总的矛盾状态。
    """
    return bool(can_access_sales(user, company) or can_access_purchase(user, company))


def can_view_sales_reports(user):
    return bool(can_access_sales(user) or _has_group(user, "report_viewer"))


def can_view_purchase_reports(user):
    return bool(can_access_purchase(user) or _has_group(user, "report_viewer"))


def can_edit_customer(user, customer):
    """能否维护这个客户的资料，以及用它录日报。

    判断依据是绑定关系，不是「谁录的」：客户归属决定谁负责维护这条主数据。
    可见范围已经放开到全公司，所以写权限必须独立判断，不能再靠 queryset 收窄
    当对象权限用——那样别人的记录会变成本公司全员可写。
    """
    if is_administrator(user):
        return True
    if is_read_only(user):
        return False
    return SalesAssignment.objects.filter(user=user, customer=customer).exists()


def can_edit_supplier(user, supplier):
    if is_administrator(user):
        return True
    if is_read_only(user):
        return False
    return PurchaseAssignment.objects.filter(user=user, supplier=supplier).exists()


def can_edit_shipment(user, shipment):
    """能否改这条销售日报：看的是当前用户与该客户的绑定关系。"""
    return can_edit_customer(user, shipment.customer)


def can_edit_receipt(user, receipt):
    return can_edit_supplier(user, receipt.supplier)


def editable_customer_ids(user, company):
    """当前用户有权维护的客户 id 集合，供列表页一次性判断整页的按钮。

    返回 None 表示不受限（管理员）——逐行调 can_edit_customer 会变成每行一次
    查询，50 行就是 50 次。
    """
    if is_administrator(user):
        return None
    if is_read_only(user) or company is None:
        return set()
    return set(
        SalesAssignment.objects.filter(user=user, customer__company=company).values_list(
            "customer_id", flat=True
        )
    )


def editable_supplier_ids(user, company):
    if is_administrator(user):
        return None
    if is_read_only(user) or company is None:
        return set()
    return set(
        PurchaseAssignment.objects.filter(user=user, supplier__company=company).values_list(
            "supplier_id", flat=True
        )
    )


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
