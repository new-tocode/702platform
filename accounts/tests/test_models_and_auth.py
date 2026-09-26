"""账号模型与登录：建号即带出个人资料、首次登录强制改密、改密后才解锁成员区。"""

from io import BytesIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from core.models import AuditLog
from ..forms import AdminUserChangeForm, AdminUserCreationForm, ProfileForm


User = get_user_model()


class AccountModelAcceptanceTests(TestCase):
    def test_member_accounts_require_first_password_change_and_get_profile(self):
        user = User.objects.create_user(
            username="member-001",
            password="Initial-Password-123!",
        )

        user.refresh_from_db()
        self.assertTrue(user.must_change_password)
        self.assertTrue(hasattr(user, "profile"))
        self.assertEqual(user.profile.user_id, user.pk)

    def test_superuser_created_by_manager_is_not_forced_to_change_password(self):
        user = User.objects.create_superuser(
            username="admin-001",
            password="Admin-Password-123!",
        )

        self.assertFalse(user.must_change_password)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)

    def test_name_is_one_field_in_member_and_admin_forms(self):
        member_fields = ProfileForm().fields
        creation_fields = AdminUserCreationForm().fields
        change_fields = AdminUserChangeForm(instance=User(username="form-user")).fields

        self.assertIn("full_name", member_fields)
        self.assertIn("full_name", creation_fields)
        self.assertIn("full_name", change_fields)
        self.assertNotIn("first_name", creation_fields)
        self.assertNotIn("last_name", creation_fields)
        self.assertNotIn("first_name", change_fields)
        self.assertNotIn("last_name", change_fields)


class MemberAuthenticationAcceptanceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="member-001",
            password="Initial-Password-123!",
            email="member@example.com",
        )

    def login_with_initial_password(self):
        return self.client.post(
            reverse("accounts:login"),
            {
                "username": self.user.username,
                "password": "Initial-Password-123!",
            },
        )

    def complete_first_password_change(self):
        self.login_with_initial_password()
        return self.client.post(
            reverse("accounts:password_change"),
            {
                "new_password1": "New-Password-456!",
                "new_password2": "New-Password-456!",
            },
        )

    def test_home_is_public_and_no_registration_route_exists(self):
        response = self.client.get(reverse("accounts:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "不开放公开注册")
        self.assertEqual(self.client.get("/register/").status_code, 404)

    def test_initial_login_redirects_directly_to_password_change(self):
        response = self.login_with_initial_password()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("accounts:password_change"))
        self.assertTrue(response.cookies)

    def test_forced_user_cannot_visit_member_features_before_password_change(self):
        self.login_with_initial_password()

        response = self.client.get(reverse("accounts:member_home"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:password_change"), response["Location"])
        self.assertIn("next=%2Fmember%2F", response["Location"])

    def test_first_password_change_unlocks_member_area_and_updates_flag(self):
        response = self.complete_first_password_change()

        self.user.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("accounts:member_home"))
        self.assertFalse(self.user.must_change_password)
        self.assertTrue(self.user.check_password("New-Password-456!"))
        self.assertEqual(self.client.get(reverse("accounts:member_home")).status_code, 200)

    def test_password_change_writes_safe_audit_event(self):
        self.complete_first_password_change()

        audit = AuditLog.objects.get(action="accounts.password.change")
        self.assertEqual(audit.user, self.user)
        self.assertEqual(audit.target_id, str(self.user.pk))
        self.assertEqual(audit.detail, {"forced_flow": True})
        self.assertNotIn("New-Password-456!", str(audit.detail))

    def test_forced_user_can_only_use_password_change_and_logout(self):
        self.login_with_initial_password()

        profile_response = self.client.get(reverse("accounts:profile"))
        password_response = self.client.get(reverse("accounts:password_change"))

        self.assertEqual(profile_response.status_code, 302)
        self.assertEqual(password_response.status_code, 200)
        self.assertContains(password_response, "请先修改初始密码")

    def test_member_can_update_profile_after_unlocking(self):
        self.complete_first_password_change()

        response = self.client.post(
            reverse("accounts:profile"),
            {
                "student_id": "20260001",
                "full_name": "成员一",
                "college": "计算机学院",
                "major": "软件工程",
                "specialty": "算法设计、机器人调试",
                "phone": "13800000000",
                "contact": "竞赛社团成员",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.full_name, "成员一")
        self.assertEqual(self.user.profile.student_id, "20260001")
        self.assertEqual(self.user.profile.college, "计算机学院")
        self.assertEqual(self.user.profile.specialty, "算法设计、机器人调试")

    def test_later_password_change_requires_old_password(self):
        self.complete_first_password_change()

        bad_response = self.client.post(
            reverse("accounts:password_change"),
            {
                "old_password": "wrong-password",
                "new_password1": "Another-Password-789!",
                "new_password2": "Another-Password-789!",
            },
        )
        self.assertEqual(bad_response.status_code, 200)
        self.assertContains(bad_response, "当前密码不正确")

        good_response = self.client.post(
            reverse("accounts:password_change"),
            {
                "old_password": "New-Password-456!",
                "new_password1": "Another-Password-789!",
                "new_password2": "Another-Password-789!",
            },
        )
        self.assertEqual(good_response.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Another-Password-789!"))
        self.assertFalse(self.user.must_change_password)

    def test_password_change_rejects_external_redirect(self):
        self.login_with_initial_password()

        response = self.client.post(
            f"{reverse('accounts:password_change')}?next=https://evil.example/",
            {
                "new_password1": "New-Password-456!",
                "new_password2": "New-Password-456!",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("accounts:member_home"))

    def test_failed_login_log_does_not_contain_password(self):
        with self.assertLogs("accounts", level="WARNING") as captured:
            response = self.client.post(
                reverse("accounts:login"),
                {
                    "username": self.user.username,
                    "password": "never-log-this-password",
                },
            )

        self.assertEqual(response.status_code, 200)
        combined_logs = "\n".join(captured.output)
        self.assertIn("auth.login.failure", combined_logs)
        self.assertNotIn("never-log-this-password", combined_logs)


