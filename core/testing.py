"""测试辅助：迁移已经预置 A、B 两家公司，这里只做取用和登录会话准备。"""

from core.models import Company
from core.services.companies import SESSION_KEY, grant_company_access


def company_a():
    return Company.objects.get(code="A")


def company_b():
    return Company.objects.get(code="B")


def login_with_company(client, user, company):
    """force_login 不会走登录表单，所以要手工把当前公司写进会话。"""
    grant_company_access(user, [company])
    client.force_login(user)
    session = client.session
    session[SESSION_KEY] = company.pk
    session.save()
