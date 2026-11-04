from core.services.permissions import is_administrator


def can_view_erp_analysis(user):
    return bool(user.is_authenticated and (is_administrator(user) or user.groups.filter(name="report_viewer").exists()))
