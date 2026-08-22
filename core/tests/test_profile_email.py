from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from core.models import CompanyMembership, UserProfile
from core.testing import company_a, login_with_company


class FirstLoginEmailTests(TestCase):
    """首次登录必须同时设置邮箱，否则后续没有地址可推送。"""

    def setUp(self):
        self.user = User.objects.create_user("sales-a", password="Initial@123")
        self.user.groups.add(Group.objects.get(name="sales"))
        CompanyMembership.objects.create(user=self.user, company=company_a())
        UserProfile.objects.update_or_create(user=self.user, defaults={"must_change_password": True})
        self.client.force_login(self.user)

    def test_the_form_asks_for_an_email(self):
        response = self.client.get(reverse("core:password_change"))

        self.assertContains(response, "本人邮箱")
        self.assertContains(response, "用于接收日报推送")

    def test_password_change_without_an_email_is_rejected(self):
        response = self.client.post(
            reverse("core:password_change"),
            {"old_password": "Initial@123", "new_password1": "New@123456", "new_password2": "New@123456"},
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Initial@123"))
        self.assertTrue(UserProfile.objects.get(user=self.user).must_change_password)

    def test_invalid_email_is_rejected(self):
        response = self.client.post(
            reverse("core:password_change"),
            {
                "email": "not-an-email",
                "old_password": "Initial@123",
                "new_password1": "New@123456",
                "new_password2": "New@123456",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(UserProfile.objects.get(user=self.user).must_change_password)

    def test_email_already_used_by_another_account_is_rejected(self):
        User.objects.create_user("other", email="taken@example.com")

        response = self.client.post(
            reverse("core:password_change"),
            {
                "email": "taken@example.com",
                "old_password": "Initial@123",
                "new_password1": "New@123456",
                "new_password2": "New@123456",
            },
        )

        self.assertContains(response, "该邮箱已被其他账号使用")

    def test_email_and_password_are_saved_together(self):
        response = self.client.post(
            reverse("core:password_change"),
            {
                "email": "sales-a@example.com",
                "old_password": "Initial@123",
                "new_password1": "New@123456",
                "new_password2": "New@123456",
            },
        )

        self.assertRedirects(response, reverse("sales:shipment_list"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "sales-a@example.com")
        self.assertTrue(self.user.check_password("New@123456"))
        self.assertFalse(UserProfile.objects.get(user=self.user).must_change_password)


class ProfileEmailTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("sales-a", email="old@example.com")
        self.user.groups.add(Group.objects.get(name="sales"))
        login_with_company(self.client, self.user, company_a())

    def test_user_can_change_their_own_email_later(self):
        response = self.client.post(reverse("core:profile_edit"), {"email": "new@example.com"})

        self.assertRedirects(response, reverse("core:profile_edit"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "new@example.com")

    def test_current_email_is_prefilled(self):
        response = self.client.get(reverse("core:profile_edit"))

        self.assertContains(response, "old@example.com")

    def test_blank_email_is_rejected(self):
        response = self.client.post(reverse("core:profile_edit"), {"email": ""})

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "old@example.com")

    def test_email_taken_by_another_account_is_rejected(self):
        User.objects.create_user("other", email="taken@example.com")

        response = self.client.post(reverse("core:profile_edit"), {"email": "taken@example.com"})

        self.assertContains(response, "该邮箱已被其他账号使用")
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "old@example.com")

    def test_anonymous_user_is_redirected_to_login(self):
        self.client.logout()

        response = self.client.get(reverse("core:profile_edit"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])
