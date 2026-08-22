"""界面兜底：403/404 要给能看懂的页面而不是裸文本，分页选择器要真的能点。"""

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from core.models import Customer
from core.services.listing import PAGE_SIZE_CHOICES
from core.testing import company_a, login_with_company


class ForbiddenPageTests(TestCase):
    """HttpResponseForbidden 返回的是无导航、无返回链接的裸文本，
    用户被卡在白屏上只能按浏览器后退。"""

    def setUp(self):
        self.company = company_a()
        self.seller = User.objects.create_user("seller")
        self.seller.groups.add(Group.objects.get(name="sales"))
        login_with_company(self.client, self.seller, self.company)

    def test_page_level_forbidden_renders_with_navigation(self):
        response = self.client.get(reverse("core:user_list"))

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "只有管理员可以管理用户", status_code=403)
        # 套了 base.html：能看到导航和帮助入口，不是一段无处可去的文字。
        self.assertContains(response, "没有权限", status_code=403)
        self.assertContains(response, "销售", status_code=403)

    def test_forbidden_page_explains_what_to_do(self):
        response = self.client.get(reverse("core:user_list"))

        self.assertContains(response, "联系管理员", status_code=403)

    def test_import_api_still_returns_plain_text_for_fetch(self):
        """导入接口是 fetch 调用的，给它 HTML 会让 response.json() 解析失败。"""
        response = self.client.post(reverse("sales:import_preview"))

        self.assertEqual(response.status_code, 403)
        self.assertNotIn(b"<!doctype", response.content.lower())
        self.assertNotIn(b"<html", response.content.lower())

    def test_dashboard_api_still_returns_plain_text_for_fetch(self):
        purchase_only = User.objects.create_user("buyer")
        purchase_only.groups.add(Group.objects.get(name="purchase"))
        login_with_company(self.client, purchase_only, self.company)

        response = self.client.get(reverse("reports:sales_dashboard_api"))

        self.assertEqual(response.status_code, 403)
        self.assertNotIn(b"<html", response.content.lower())


class NotFoundPageTests(TestCase):
    def setUp(self):
        admin = User.objects.create_superuser("admin", password="pw")
        login_with_company(self.client, admin, company_a())

    def test_missing_record_renders_the_custom_404(self):
        with self.settings(DEBUG=False, ALLOWED_HOSTS=["*"]):
            response = self.client.get(reverse("sales:shipment_edit", args=[999999]))

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "页面不存在", status_code=404)


class TitleTests(TestCase):
    """同时开着 A、B 两家公司的标签页时，标签必须能分辨，否则容易看错数据。"""

    def test_title_carries_the_active_company(self):
        admin = User.objects.create_superuser("admin", password="pw")
        company = company_a()
        login_with_company(self.client, admin, company)

        response = self.client.get(reverse("sales:shipment_list"))

        self.assertContains(response, f"<title>{company.name} - FINOSSReportSystem</title>")


class PageSizeSelectorTests(TestCase):
    """listing.paginate 一直支持 size 参数，但界面上没有入口，等于点不到。"""

    def setUp(self):
        self.admin = User.objects.create_superuser("admin", password="pw")
        self.company = company_a()
        # 造出多于一页的数据，分页控件才会渲染
        Customer.objects.bulk_create(
            [Customer(company=self.company, name=f"客户{index:03d}") for index in range(60)]
        )
        login_with_company(self.client, self.admin, self.company)

    def test_the_selector_is_rendered_with_every_choice(self):
        response = self.client.get(reverse("core:customer_list"))

        self.assertContains(response, 'name="size"')
        for choice in PAGE_SIZE_CHOICES:
            self.assertContains(response, f'value="{choice}"')

    def test_choosing_a_size_changes_the_rows_per_page(self):
        response = self.client.get(reverse("core:customer_list"), {"size": 20})

        self.assertEqual(len(response.context["page"].object_list), 20)
        self.assertEqual(response.context["page"].current_size, 20)

    def test_an_unsupported_size_falls_back_to_the_default(self):
        """手改 URL 传 size=99999 不该一次拉出全表。"""
        response = self.client.get(reverse("core:customer_list"), {"size": 99999})

        self.assertEqual(response.context["page"].current_size, 50)

    def test_paging_keeps_the_chosen_size(self):
        response = self.client.get(reverse("core:customer_list"), {"size": 20, "page": 2})

        self.assertEqual(response.context["page"].current_size, 20)
        self.assertIn("size=20", response.context["querystring"])

    def test_the_selector_keeps_the_current_search_term(self):
        response = self.client.get(reverse("core:customer_list"), {"q": "客户0", "size": 20})

        self.assertContains(response, 'name="q"')
        self.assertContains(response, 'value="客户0"')
