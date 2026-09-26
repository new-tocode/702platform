"""身份名册与批量授予：给谁发了资格、留了什么痕。"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from core.models import AuditLog
from ..services import set_qualification


User = get_user_model()


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

    def test_view_only_observer_cannot_submit_a_qualification_action(self):
        """只读观察者不该发得出资格——这是这批动作唯一的 HTTP 门槛。

        ``set_qualification`` 是给程序调用的服务函数，不看请求是谁发的；因此
        「谁提交了这个动作」只在 ``@admin.action`` 的 ``permissions`` 白名单上
        把关。漏声明时 Django 对所有人放行，于是一个只挂 ``view_user`` 的账号
        能给自己或他人发资格——甚至能把目标推成超级评审。
        """
        observer = User.objects.create_user(
            username="view-only-observer",
            password="Observer-Password-123!",
        )
        observer.must_change_password = False
        observer.is_staff = True
        observer.save(update_fields=["must_change_password", "is_staff"])
        observer.user_permissions.add(
            Permission.objects.get(codename="view_user")
        )
        target = self._member("bulk-target", "被选中的人")

        # 看得到列表，但页面上没有这个动作可挑。
        self.client.force_login(observer)
        listing = reverse("admin:accounts_user_changelist")
        page = self.client.get(listing)
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "grant_is_reviewer")

        # 绕过页面直接 POST 也不行。
        self.client.post(
            listing,
            {
                "action": "grant_is_reviewer",
                "_selected_action": [str(target.pk)],
                "index": "0",
            },
            follow=True,
        )
        target.refresh_from_db()
        observer.refresh_from_db()
        self.assertFalse(target.is_reviewer)

        # 连给自己发也不行——提权路径本来从这里开始。
        self.client.post(
            listing,
            {
                "action": "grant_is_super_reviewer",
                "_selected_action": [str(observer.pk)],
                "index": "0",
            },
            follow=True,
        )
        observer.refresh_from_db()
        self.assertFalse(observer.is_super_reviewer)

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

