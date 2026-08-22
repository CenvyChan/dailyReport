from core.models import Company, CompanyMembership
from core.services.permissions import is_administrator


SESSION_KEY = "active_company_id"


def company_queryset_for(user):
    """管理员可进入全部启用公司；其他用户只能进入被授权的公司。"""
    companies = Company.objects.filter(is_active=True)
    if is_administrator(user):
        return companies
    return companies.filter(companymembership__user=user)


def can_access_company(user, company):
    return company_queryset_for(user).filter(pk=company.pk).exists()


def set_active_company(session, company):
    session[SESSION_KEY] = company.pk


def active_company_for(request):
    """读取会话里的公司；失效或越权时回退到该用户的第一家公司。"""
    allowed = company_queryset_for(request.user)
    company_id = request.session.get(SESSION_KEY)
    company = allowed.filter(pk=company_id).first() if company_id else None
    if company is None:
        company = allowed.first()
        if company is not None:
            set_active_company(request.session, company)
    return company


def grant_company_access(user, companies):
    for company in companies:
        CompanyMembership.objects.get_or_create(user=user, company=company)
