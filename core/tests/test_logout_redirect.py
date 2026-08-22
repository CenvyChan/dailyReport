from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from core.models import CompanyMembership, UserProfile
from core.testing import company_a


class LogoutRedirectTests(TestCase):
    """注销后必须回到业务登录页。之前没设 next_page，会停在 Django admin
    的注销模板上，用户再登录就被带去 /admin/ 而不是日报。"""

    def setUp(self):
        self.user = User.objects.create_user("u1", password="pw", first_name="张三")
        self.user.groups.add(Group.objects.get(name="sales"))
        CompanyMembership.objects.create(user=self.user, company=company_a())
        UserProfile.objects.update_or_create(user=self.user, defaults={"must_change_password": False})

    def _login(self):
        return self.client.post(
            reverse("login"),
            {"username": "u1", "password": "pw", "company": company_a().pk},
        )

    def test_login_lands_on_the_sales_page(self):
        self.assertRedirects(self._login(), reverse("sales:shipment_list"))

    def test_logout_returns_to_the_business_login_page(self):
        self._login()

        response = self.client.post(reverse("logout"))

        self.assertRedirects(response, reverse("login"))
        self.assertNotIn("/admin/", response.headers.get("Location", ""))

    def test_visiting_a_business_page_after_logout_asks_to_log_in_again(self):
        self._login()
        self.client.post(reverse("logout"))

        response = self.client.get(reverse("sales:shipment_list"))

        self.assertEqual(
            response.headers["Location"],
            f"{reverse('login')}?next={reverse('sales:shipment_list')}",
        )

    def test_logging_in_again_after_logout_reaches_the_sales_page(self):
        self._login()
        self.client.post(reverse("logout"))

        self.assertRedirects(self._login(), reverse("sales:shipment_list"))
