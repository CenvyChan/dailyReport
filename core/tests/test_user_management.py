from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from core.models import UserProfile


class UserManagementTests(TestCase):
    def test_administrator_can_create_user_with_role_and_first_login_change(self):
        admin = User.objects.create_superuser("admin", password="pw")
        self.client.force_login(admin)

        response = self.client.post(
            reverse("core:user_create"),
            {"username": "sales-a", "first_name": "销售甲", "role": "sales", "password": "Initial@123"},
        )

        self.assertRedirects(response, reverse("core:user_list"))
        user = User.objects.get(username="sales-a")
        self.assertEqual(user.first_name, "销售甲")
        self.assertTrue(user.groups.filter(name="sales").exists())
        self.assertTrue(UserProfile.objects.get(user=user).must_change_password)

    def test_first_login_redirects_to_change_password_and_clears_flag(self):
        user = User.objects.create_user("sales-a", password="Initial@123")
        user.groups.add(Group.objects.get(name="sales"))
        UserProfile.objects.update_or_create(user=user, defaults={"must_change_password": True})

        response = self.client.post(
            reverse("login"),
            {"username": "sales-a", "password": "Initial@123"},
        )

        self.assertRedirects(response, reverse("core:password_change"))
        response = self.client.post(
            reverse("core:password_change"),
            {"old_password": "Initial@123", "new_password1": "New@123456", "new_password2": "New@123456"},
        )
        self.assertRedirects(response, reverse("sales:shipment_list"))
        self.assertFalse(UserProfile.objects.get(user=user).must_change_password)

    def test_non_administrator_cannot_manage_users(self):
        user = User.objects.create_user("sales-a")
        self.client.force_login(user)

        self.assertEqual(self.client.get(reverse("core:user_list")).status_code, 403)

    def test_create_user_page_uses_chinese_roles_and_explains_initial_password(self):
        admin = User.objects.create_superuser("admin", password="pw")
        self.client.force_login(admin)

        response = self.client.get(reverse("core:user_create"))

        self.assertContains(response, "管理员")
        self.assertContains(response, "销售")
        self.assertContains(response, "采购")
        self.assertContains(response, "报表查看者")
        self.assertContains(response, "首次登录后必须自行修改")

    def test_duplicate_username_is_shown_as_chinese_form_error(self):
        admin = User.objects.create_superuser("admin", password="pw")
        User.objects.create_user("sales-a")
        self.client.force_login(admin)

        response = self.client.post(
            reverse("core:user_create"),
            {"username": "sales-a", "first_name": "销售甲", "role": "sales", "password": "Initial@123"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "用户名已存在，请更换后再保存")
