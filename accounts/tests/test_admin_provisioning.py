"""后台发账号与改密：建号、重置密码、非 staff 进不去。"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse



User = get_user_model()


class AdminProvisioningAcceptanceTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin-001",
            password="Admin-Password-123!",
        )
        self.client.force_login(self.admin)

    def test_admin_can_create_member_with_forced_change_flag(self):
        response = self.client.post(
            reverse("admin:accounts_user_add"),
            {
                "username": "member-002",
                "email": "member2@example.com",
                "full_name": "成员二",
                "password1": "Initial-Password-234!",
                "password2": "Initial-Password-234!",
                "_save": "保存",
            },
        )

        self.assertIn(response.status_code, {200, 302})
        member = User.objects.get(username="member-002")
        self.assertTrue(member.must_change_password)
        self.assertEqual(member.profile.full_name, "成员二")
        self.assertTrue(member.check_password("Initial-Password-234!"))

    def test_admin_user_editor_exposes_one_name_field(self):
        member = User.objects.create_user(
            username="member-name-editor",
            password="Initial-Password-678!",
        )
        member.profile.full_name = "已有姓名"
        member.profile.save(update_fields=["full_name"])

        response = self.client.get(
            reverse("admin:accounts_user_change", args=(member.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="full_name"')
        self.assertContains(response, "已有姓名")
        self.assertNotContains(response, 'name="first_name"')
        self.assertNotContains(response, 'name="last_name"')

    def test_admin_password_reset_restarts_forced_change_cycle(self):
        member = User.objects.create_user(
            username="member-003",
            password="Old-Password-345!",
        )
        member.must_change_password = False
        member.save(update_fields=["must_change_password"])

        response = self.client.post(
            reverse("admin:auth_user_password_change", args=(member.pk,)),
            {
                "password1": "Reset-Password-567!",
                "password2": "Reset-Password-567!",
                "usable_password": "true",
                "_save": "保存",
            },
        )

        self.assertEqual(response.status_code, 302)
        member.refresh_from_db()
        self.assertTrue(member.must_change_password)
        self.assertTrue(member.check_password("Reset-Password-567!"))

    def test_admin_can_open_user_list_but_member_cannot_use_admin(self):
        response = self.client.get(reverse("admin:accounts_user_changelist"))
        self.assertEqual(response.status_code, 200)

        member = User.objects.create_user(
            username="member-004",
            password="Initial-Password-456!",
        )
        self.client.force_login(member)
        member_admin_response = self.client.get("/admin/")
        self.assertEqual(member_admin_response.status_code, 302)

    def test_admin_group_pages_load_and_list_group_members(self):
        member = User.objects.create_user(
            username="member-in-group",
            password="Initial-Password-789!",
        )
        member.profile.full_name = "组内成员"
        member.profile.save(update_fields=["full_name"])
        group = Group.objects.create(name="测试用户组")
        member.groups.add(group)

        list_response = self.client.get(reverse("admin:auth_group_changelist"))
        change_response = self.client.get(
            reverse("admin:auth_group_change", args=(group.pk,))
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, "测试用户组")
        self.assertEqual(change_response.status_code, 200)
        self.assertContains(change_response, "组内成员")


