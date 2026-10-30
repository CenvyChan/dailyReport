from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from core.models import CompanyMembership, UserProfile
from core.testing import company_a, login_with_company


class UserGuideTests(TestCase):
    def test_guide_is_reachable_without_logging_in(self):
        """登录页上的帮助入口必须匿名可访问，否则点了会被弹回登录页。"""
        response = self.client.get(reverse("core:user_guide"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response["Content-Type"])
        self.assertIn("charset=utf-8", response["Content-Type"])

    def test_guide_serves_the_document_from_docs_guide(self):
        response = self.client.get(reverse("core:user_guide"))
        body = response.content.decode("utf-8")

        self.assertIn("用户使用指南", body)
        self.assertIn("登录与选择公司", body)
        self.assertIn("导入历史数据", body)

    def test_login_page_links_to_the_guide_with_a_help_icon(self):
        response = self.client.get(reverse("login"))

        self.assertContains(response, reverse("core:user_guide"))
        self.assertContains(response, "帮助信息")
        self.assertContains(response, "help-icon")

    def test_guide_explains_what_to_do_without_company_access(self):
        """登录页不再堆说明文字，权限问题统一放到指南的常见问题里。"""
        response = self.client.get(reverse("core:user_guide"))

        self.assertContains(response, "没有可进入的公司")
        self.assertContains(response, "用户公司授权")

    def test_guide_uses_sticky_sidebar_layout(self):
        """目录固定在左侧，长文滚动时仍然可见；顶栏提供 Ctrl+K 搜索。"""
        response = self.client.get(reverse("core:user_guide"))

        self.assertContains(response, 'class="sidebar"')
        self.assertContains(response, 'class="doc-search"')
        self.assertContains(response, 'id="guide-search"')
        self.assertContains(response, "toc-group")
        self.assertContains(response, "Ctrl K")

    def test_guide_shows_default_credentials(self):
        """新同事第一次登录要用：用户名是姓名全拼，默认密码可点击复制。"""
        response = self.client.get(reverse("core:user_guide"))

        self.assertContains(response, "姓名全拼")
        self.assertContains(response, "fns112233.")
        self.assertContains(response, 'data-copy="fns112233."')

    def test_login_page_shows_the_new_brand(self):
        response = self.client.get(reverse("login"))

        self.assertContains(response, "FINOSSReportSystem")
        self.assertNotContains(response, "轻量日报")

    def test_signed_in_navigation_also_offers_the_guide(self):
        user = User.objects.create_user("sales-a")
        user.groups.add(Group.objects.get(name="sales"))
        login_with_company(self.client, user, company_a())

        response = self.client.get(reverse("sales:shipment_list"))

        self.assertContains(response, reverse("core:user_guide"))

    def test_guide_stays_reachable_while_a_password_change_is_pending(self):
        """首次登录会被中间件锁在改密页，帮助必须仍然打得开。"""
        user = User.objects.create_user("sales-a", password="Initial@123")
        user.groups.add(Group.objects.get(name="sales"))
        CompanyMembership.objects.create(user=user, company=company_a())
        UserProfile.objects.update_or_create(user=user, defaults={"must_change_password": True})
        self.client.force_login(user)

        self.assertEqual(self.client.get(reverse("core:user_guide")).status_code, 200)
        self.assertRedirects(
            self.client.get(reverse("sales:shipment_list")), reverse("core:password_change")
        )
