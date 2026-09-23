"""Stage 1 acceptance tests for accounts and forced password changes."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group
from django.test import TestCase
from django.urls import reverse

from core.models import AuditLog
from projects.models import ProjectGroup

from .forms import AdminUserChangeForm, AdminUserCreationForm, ProfileForm
from .roles import describe_member
from .services import set_qualification


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


class MemberRoleDisplayAcceptanceTests(TestCase):
    """成员中心显示当前身份；口径见 accounts/roles.py。"""

    def setUp(self):
        self.member = User.objects.create_user(
            username="role-member",
            password="Member-Password-123!",
        )
        self.contact = User.objects.create_user(
            username="role-contact",
            password="Contact-Password-123!",
        )
        self.staff = User.objects.create_user(
            username="role-staff",
            password="Staff-Password-123!",
        )
        self.staff.is_staff = True
        for user in (self.member, self.contact, self.staff):
            user.must_change_password = False
            user.save(update_fields=["must_change_password", "is_staff"])
        self.group = ProjectGroup.objects.create(name="角色测试组", leader=self.contact)

    def assert_role_cell(self, response, role):
        # 页脚也有「管理员」等字样，因此断言精确到身份单元格本身。
        self.assertContains(response, f'<div class="v text">{role}</div>')

    def test_anonymous_is_described_as_guest(self):
        self.assertEqual(describe_member(AnonymousUser()), "游客")

    def test_member_without_group_is_described_as_no_group(self):
        self.client.force_login(self.member)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertContains(response, "当前身份")
        self.assert_role_cell(response, "未加入项目组")

    def test_group_member_is_described_as_group_member(self):
        self.group.members.add(self.member)
        self.client.force_login(self.member)

        response = self.client.get(reverse("accounts:member_home"))

        self.assert_role_cell(response, "项目组成员")

    def test_contact_is_described_as_project_contact(self):
        self.client.force_login(self.contact)

        response = self.client.get(reverse("accounts:member_home"))

        self.assert_role_cell(response, "项目组联系人")

    def test_staff_is_described_as_admin(self):
        self.client.force_login(self.staff)

        response = self.client.get(reverse("accounts:member_home"))

        self.assert_role_cell(response, "管理员")

    def test_platform_overview_is_visible_to_admin_and_contact_only(self):
        for user, sees_overview in (
            (self.staff, True),
            (self.contact, True),
            (self.member, False),
        ):
            with self.subTest(username=user.username):
                self.client.force_login(user)

                response = self.client.get(reverse("accounts:member_home"))

                if sees_overview:
                    self.assertContains(response, "社团概览")
                    self.assertContains(response, "在册成员")
                else:
                    self.assertNotContains(response, "社团概览")
                    self.assertNotContains(response, "在册成员")

    def test_public_home_no_longer_exposes_platform_overview(self):
        response = self.client.get(reverse("accounts:home"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "在册成员")
        self.assertNotContains(response, "在借设备")

    def test_member_home_drops_permission_hint_and_entry_counter_box(self):
        self.client.force_login(self.member)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertNotContains(response, "可用入口按当前账号权限显示")
        self.assertNotContains(response, '<div class="k">可用入口</div>')


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


class RoleRosterAcceptanceTests(TestCase):
    """身份名册与批量授予——后台唯一能直接发放身份的地方。

    名册本身只读。全局身份的授予与撤销走用户列表页的批量动作；对象身份
    （项目组联系人、成员）连批量动作都没有，只能由业务动作产生。
    """

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin-roles",
            password="Admin-Password-123!",
        )
        self.client.force_login(self.admin)

    def _member(self, username, full_name):
        user = User.objects.create_user(
            username=username,
            password="Initial-Password-123!",
        )
        user.profile.full_name = full_name
        user.profile.save(update_fields=["full_name"])
        return user

    def test_roster_lists_exactly_the_holders(self):
        holder = self._member("roster-holder", "有名册的人")
        holder.is_reviewer = True
        holder.save(update_fields=["is_reviewer"])
        self._member("roster-outsider", "不在名册的人")

        response = self.client.get(reverse("admin:accounts_reviewerrole_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "有名册的人")
        self.assertNotContains(response, "不在名册的人")

    def test_roster_shows_every_identity_a_person_holds(self):
        holder = self._member("roster-multi", "多重身份")
        holder.is_reviewer = True
        holder.is_super_reviewer = True
        holder.save(update_fields=["is_reviewer", "is_super_reviewer"])

        response = self.client.get(reverse("admin:accounts_reviewerrole_changelist"))

        self.assertContains(response, "评审人、超级评审")

    def test_all_six_rosters_load(self):
        for name in (
            "admin:accounts_adminrole_changelist",
            "admin:accounts_reviewerrole_changelist",
            "admin:accounts_preliminaryreviewerrole_changelist",
            "admin:accounts_superreviewerrole_changelist",
            "admin:projects_projectcontact_changelist",
            "admin:projects_projectmember_changelist",
        ):
            with self.subTest(roster=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_rosters_offer_no_way_to_hand_out_an_identity(self):
        """名册能看不能发——发资格在用户列表页，对象身份则只能由业务动作产生。"""
        for name in (
            "admin:accounts_reviewerrole_add",
            "admin:projects_projectcontact_add",
            "admin:projects_projectmember_add",
        ):
            with self.subTest(add_page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 403)

    def test_bulk_action_grants_then_revokes_reviewer_qualification(self):
        first = self._member("bulk-one", "甲")
        second = self._member("bulk-two", "乙")
        selected = [str(first.pk), str(second.pk)]
        listing = reverse("admin:accounts_user_changelist")

        self.client.post(
            listing,
            {"action": "grant_is_reviewer", "_selected_action": selected, "index": "0"},
            follow=True,
        )
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertTrue(first.is_reviewer)
        self.assertTrue(second.is_reviewer)
        self.assertTrue(
            AuditLog.objects.filter(action="accounts.qualification.grant").exists()
        )

        self.client.post(
            listing,
            {"action": "revoke_is_reviewer", "_selected_action": selected, "index": "0"},
            follow=True,
        )
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_reviewer)
        self.assertFalse(second.is_reviewer)

    def test_granting_someone_who_already_has_it_leaves_no_audit_row(self):
        member = self._member("bulk-idempotent", "丙")
        member.is_reviewer = True
        member.save(update_fields=["is_reviewer"])

        self.client.post(
            reverse("admin:accounts_user_changelist"),
            {
                "action": "grant_is_reviewer",
                "_selected_action": [str(member.pk)],
                "index": "0",
            },
            follow=True,
        )

        member.refresh_from_db()
        self.assertTrue(member.is_reviewer)
        # 取值没变就不算一次授予，也就没有新的审计行。
        self.assertFalse(
            AuditLog.objects.filter(action="accounts.qualification.grant").exists()
        )

    def test_no_bulk_action_hands_out_admin_access(self):
        """把一批人放进后台该是逐个确认的事，不该由一次批量动作完成。"""
        response = self.client.get(reverse("admin:accounts_user_changelist"))

        self.assertNotContains(response, "授予管理员资格")
        self.assertNotContains(response, "撤销管理员资格")

    def test_service_refuses_flags_outside_the_allowlist(self):
        with self.assertRaises(ValueError):
            set_qualification(
                users=[self.admin],
                flag="is_superuser",
                value=True,
                actor=self.admin,
            )

    def test_new_account_can_be_given_qualifications_right_away(self):
        response = self.client.post(
            reverse("admin:accounts_user_add"),
            {
                "username": "member-with-roles",
                "email": "roles@example.com",
                "full_name": "带资格的新人",
                "password1": "Initial-Password-234!",
                "password2": "Initial-Password-234!",
                "is_reviewer": "on",
                "is_preliminary_reviewer": "on",
                "_save": "保存",
            },
        )

        self.assertIn(response.status_code, {200, 302})
        member = User.objects.get(username="member-with-roles")
        self.assertTrue(member.is_reviewer)
        self.assertTrue(member.is_preliminary_reviewer)
        self.assertFalse(member.is_super_reviewer)
