from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from core.models import CompanyMembership, UserProfile
from core.testing import company_a, company_b, login_with_company


class UserManagementTests(TestCase):
    def test_administrator_can_create_user_with_role_and_first_login_change(self):
        admin = User.objects.create_superuser("admin", password="pw")
        login_with_company(self.client, admin, company_a())

        response = self.client.post(
            reverse("core:user_create"),
            {
                "username": "sales-a",
                "first_name": "销售甲",
                "roles": ["sales"],
                "companies": [company_a().pk],
                "password": "Initial@123",
            },
        )

        self.assertRedirects(response, reverse("core:user_list"))
        user = User.objects.get(username="sales-a")
        self.assertEqual(user.first_name, "销售甲")
        self.assertTrue(user.groups.filter(name="sales").exists())
        self.assertTrue(UserProfile.objects.get(user=user).must_change_password)
        self.assertEqual(
            list(CompanyMembership.objects.filter(user=user).values_list("company__code", flat=True)),
            ["A"],
        )

    def test_user_can_be_authorised_for_both_companies_at_once(self):
        admin = User.objects.create_superuser("admin", password="pw")
        login_with_company(self.client, admin, company_a())

        self.client.post(
            reverse("core:user_create"),
            {
                "username": "shared",
                "roles": ["report_viewer"],
                "companies": [company_a().pk, company_b().pk],
                "password": "Initial@123",
            },
        )

        user = User.objects.get(username="shared")
        self.assertEqual(
            sorted(CompanyMembership.objects.filter(user=user).values_list("company__code", flat=True)),
            ["A", "B"],
        )

    def test_first_login_redirects_to_change_password_and_clears_flag(self):
        user = User.objects.create_user("sales-a", password="Initial@123")
        user.groups.add(Group.objects.get(name="sales"))
        CompanyMembership.objects.create(user=user, company=company_a())
        UserProfile.objects.update_or_create(user=user, defaults={"must_change_password": True})

        response = self.client.post(
            reverse("login"),
            {"username": "sales-a", "password": "Initial@123", "company": company_a().pk},
        )

        self.assertRedirects(response, reverse("core:password_change"))
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
        self.assertFalse(UserProfile.objects.get(user=user).must_change_password)
        user.refresh_from_db()
        self.assertEqual(user.email, "sales-a@example.com")

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
            {
                "username": "sales-a",
                "first_name": "销售甲",
                "roles": ["sales"],
                "companies": [company_a().pk],
                "password": "Initial@123",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "用户名已存在，请更换后再保存")

    def test_a_user_can_hold_several_roles_at_once(self):
        admin = User.objects.create_superuser("admin", password="pw")
        login_with_company(self.client, admin, company_a())

        response = self.client.post(
            reverse("core:user_create"),
            {
                "username": "both",
                "first_name": "兼职甲",
                "roles": ["sales", "purchase"],
                "companies": [company_a().pk],
                "password": "Initial@123",
            },
        )

        self.assertRedirects(response, reverse("core:user_list"))
        user = User.objects.get(username="both")
        self.assertEqual(sorted(user.groups.values_list("name", flat=True)), ["purchase", "sales"])
        self.assertFalse(user.is_staff)

    def test_multi_role_user_can_open_both_modules(self):
        admin = User.objects.create_superuser("admin", password="pw")
        login_with_company(self.client, admin, company_a())
        self.client.post(
            reverse("core:user_create"),
            {
                "username": "both",
                "roles": ["sales", "purchase"],
                "companies": [company_a().pk],
                "password": "Initial@123",
            },
        )
        user = User.objects.get(username="both")
        UserProfile.objects.update_or_create(user=user, defaults={"must_change_password": False})
        login_with_company(self.client, user, company_a())

        self.assertEqual(self.client.get(reverse("sales:shipment_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("purchase:receipt_list")).status_code, 200)

    def test_administrator_among_several_roles_still_gets_staff_flag(self):
        admin = User.objects.create_superuser("admin", password="pw")
        login_with_company(self.client, admin, company_a())

        self.client.post(
            reverse("core:user_create"),
            {
                "username": "boss",
                "roles": ["administrator", "sales"],
                "companies": [company_a().pk],
                "password": "Initial@123",
            },
        )

        user = User.objects.get(username="boss")
        self.assertTrue(user.is_staff)
        self.assertEqual(sorted(user.groups.values_list("name", flat=True)), ["administrator", "sales"])

    def test_creating_a_user_without_any_role_is_rejected(self):
        admin = User.objects.create_superuser("admin", password="pw")
        login_with_company(self.client, admin, company_a())

        response = self.client.post(
            reverse("core:user_create"),
            {
                "username": "norole",
                "roles": [],
                "companies": [company_a().pk],
                "password": "Initial@123",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="norole").exists())

    def test_user_list_shows_every_role_of_a_multi_role_user(self):
        admin = User.objects.create_superuser("admin", password="pw")
        user = User.objects.create_user("both")
        user.groups.set(Group.objects.filter(name__in=["sales", "purchase"]))
        CompanyMembership.objects.create(user=user, company=company_a())
        login_with_company(self.client, admin, company_a())

        response = self.client.get(reverse("core:user_list"))

        self.assertContains(response, "销售、采购")

    def test_login_is_rejected_when_the_account_lacks_that_company(self):
        user = User.objects.create_user("sales-a", password="Initial@123")
        user.groups.add(Group.objects.get(name="sales"))
        CompanyMembership.objects.create(user=user, company=company_a())

        response = self.client.post(
            reverse("login"),
            {"username": "sales-a", "password": "Initial@123", "company": company_b().pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "当前账号没有该公司的访问权限")


class DeactivateAccountTests(TestCase):
    """员工离职是日常动作，此前必须进 Django admin 改 is_active。
    用停用而不是删除：日报的 owner/buyer 是 PROTECT，而且历史数据要保留归属人。"""

    def setUp(self):
        self.admin = User.objects.create_superuser("admin", password="pw")
        self.company = company_a()
        self.staff = User.objects.create_user("leaver", first_name="离职员工")
        self.staff.groups.add(Group.objects.get(name="sales"))
        login_with_company(self.client, self.admin, self.company)

    def _toggle(self, user, activate):
        return self.client.post(
            reverse("core:user_set_active", args=[user.pk]),
            {"is_active": "1" if activate else "0"},
            follow=True,
        )

    def test_administrator_can_deactivate_from_the_user_list(self):
        response = self._toggle(self.staff, False)

        self.staff.refresh_from_db()
        self.assertFalse(self.staff.is_active)
        self.assertContains(response, "已停用")

    def test_a_deactivated_account_cannot_log_in(self):
        self.staff.set_password("pw12345")
        self.staff.save()
        self._toggle(self.staff, False)
        self.client.logout()

        logged_in = self.client.login(username="leaver", password="pw12345")

        self.assertFalse(logged_in)

    def test_deactivating_keeps_the_historical_reports(self):
        from datetime import date

        from core.models import Customer
        from sales.models import SalesShipment

        customer = Customer.objects.create(company=self.company, name="客户甲")
        SalesShipment.objects.create(
            company=self.company,
            customer=customer,
            owner=self.staff,
            sale_type="DOMESTIC",
            shipment_date=date(2026, 8, 10),
            quantity=1,
            currency="CNY",
            original_amount="10.00",
            exchange_rate="1.0000",
            amount_cny="10.00",
        )

        self._toggle(self.staff, False)

        self.assertEqual(SalesShipment.objects.filter(owner=self.staff).count(), 1)

    def test_a_deactivated_account_can_be_enabled_again(self):
        self._toggle(self.staff, False)

        self._toggle(self.staff, True)

        self.staff.refresh_from_db()
        self.assertTrue(self.staff.is_active)

    def test_administrator_cannot_deactivate_themselves(self):
        response = self._toggle(self.admin, False)

        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)
        self.assertContains(response, "不能停用自己")

    def test_the_last_active_administrator_is_protected(self):
        """停掉最后一个管理员就没人能管系统了，只能去命令行救。

        直接测 service 层：走界面的话「不能停用自己」那条规则会先命中，
        碰不到这一条。
        """
        from core.services.users import set_user_active

        # setUp 里只有 self.admin 一个管理员，再建一个用来做操作人。
        operator = User.objects.create_superuser("admin2", password="pw")
        # 停掉 operator，让 self.admin 成为唯一启用的管理员。
        set_user_active(actor=self.admin, user=operator, is_active=False)

        with self.assertRaises(PermissionError) as caught:
            set_user_active(actor=self.admin, user=self.admin, is_active=False)

        # 自己这条先命中「不能停用自己」，所以换个已停用的管理员启用回来再试。
        set_user_active(actor=self.admin, user=operator, is_active=True)
        set_user_active(actor=operator, user=self.admin, is_active=False)
        with self.assertRaises(PermissionError) as last_one:
            set_user_active(actor=self.admin, user=operator, is_active=False)

        self.assertIn("不能停用自己", str(caught.exception))
        self.assertIn("最后一个启用的管理员", str(last_one.exception))

    def test_one_of_several_administrators_can_be_deactivated(self):
        spare = User.objects.create_user("admin2")
        spare.groups.add(Group.objects.get(name="administrator"))

        self._toggle(spare, False)

        spare.refresh_from_db()
        self.assertFalse(spare.is_active)

    def test_the_toggle_is_audited(self):
        from core.models import OperationLog

        self._toggle(self.staff, False)

        log = OperationLog.objects.filter(action="DEACTIVATE").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.actor, self.admin)
        self.assertEqual(log.after_data["is_active"], False)

    def test_non_administrator_cannot_toggle(self):
        seller = User.objects.create_user("seller")
        seller.groups.add(Group.objects.get(name="sales"))
        login_with_company(self.client, seller, self.company)

        response = self.client.post(
            reverse("core:user_set_active", args=[self.staff.pk]), {"is_active": "0"}
        )

        self.assertEqual(response.status_code, 403)
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.is_active)

    def test_get_requests_do_not_change_state(self):
        response = self.client.get(reverse("core:user_set_active", args=[self.staff.pk]))

        self.assertEqual(response.status_code, 403)
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.is_active)

    def test_the_list_hides_the_button_for_accounts_that_cannot_be_toggled(self):
        response = self.client.get(reverse("core:user_list"))

        # 自己那一行不该出现停用按钮。
        self.assertContains(response, reverse("core:user_set_active", args=[self.staff.pk]))
        self.assertNotContains(response, reverse("core:user_set_active", args=[self.admin.pk]))


class PasswordStrengthTests(TestCase):
    """AUTH_PASSWORD_VALIDATORS 只对 Django 自带的改密表单自动生效，
    管理员设初始密码这条路径要手工接上，否则能设成 "1"。"""

    def setUp(self):
        self.admin = User.objects.create_superuser("admin", password="pw")
        login_with_company(self.client, self.admin, company_a())

    def _create(self, password):
        return self.client.post(
            reverse("core:user_create"),
            {
                "username": "newbie",
                "first_name": "新人",
                "roles": ["sales"],
                "companies": [company_a().pk],
                "password": password,
            },
        )

    def test_a_one_character_initial_password_is_rejected(self):
        response = self._create("1")

        self.assertFalse(User.objects.filter(username="newbie").exists())
        self.assertContains(response, "至少")

    def test_an_all_numeric_password_is_rejected(self):
        response = self._create("12345678")

        self.assertFalse(User.objects.filter(username="newbie").exists())
        self.assertContains(response, "数字")

    def test_a_common_password_is_rejected(self):
        response = self._create("password")

        self.assertFalse(User.objects.filter(username="newbie").exists())
        self.assertContains(response, "常见")

    def test_a_reasonable_password_is_accepted(self):
        response = self._create("Fns@2026Init")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username="newbie").exists())

    def test_password_reset_enforces_the_same_rules(self):
        target = User.objects.create_user("someone")

        response = self.client.post(
            reverse("core:user_password_reset", args=[target.pk]), {"password": "1"}
        )

        self.assertContains(response, "至少")
        target.refresh_from_db()
        self.assertFalse(target.check_password("1"))
