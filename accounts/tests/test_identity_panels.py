"""「当前身份」与成员角色显示：只列实际持有的身份，对象身份带组名。"""

import re

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase
from django.urls import reverse

from projects.models import ProjectGroup
from ..roles import describe_member


User = get_user_model()


class ProfileIdentityPanelAcceptanceTests(TestCase):
    """个人信息页右栏的「当前身份」：只列实际持有的，对象身份带组名。"""

    def setUp(self):
        self.member = User.objects.create_user(
            username="identity-member",
            password="Member-Password-123!",
        )
        self.member.must_change_password = False
        self.member.save(update_fields=["must_change_password"])
        self.client.force_login(self.member)

    def identities_on_page(self):
        """页面上这一栏画出来的身份标签与组名，各按出现顺序。

        整页只有这一处会画身份标签（``.chip-on``）与组名（``.member``），
        所以不用先切出面板那一段。
        """
        html = self.client.get(reverse("accounts:profile")).content.decode()
        return (
            re.findall(r'<span class="chip chip-on">(.*?)</span>', html),
            re.findall(r'<span class="member">(.*?)</span>', html),
        )

    def test_a_member_without_extra_identities_sees_an_empty_note(self):
        response = self.client.get(reverse("accounts:profile"))
        labels, groups = self.identities_on_page()

        self.assertEqual(labels, [])
        self.assertEqual(groups, [])
        self.assertContains(response, "暂无其他身份")

    def test_every_held_identity_is_listed_in_catalog_order(self):
        self.member.is_staff = True
        self.member.is_reviewer = True
        self.member.is_super_reviewer = True
        self.member.save(
            update_fields=["is_staff", "is_reviewer", "is_super_reviewer"]
        )

        labels, _groups = self.identities_on_page()

        self.assertEqual(labels, ["管理员", "评审人", "超级评审"])

    def test_qualifications_left_off_are_not_listed(self):
        self.member.is_preliminary_reviewer = True
        self.member.save(update_fields=["is_preliminary_reviewer"])

        labels, _groups = self.identities_on_page()

        self.assertEqual(labels, ["初审人"])

    def test_object_identities_carry_their_group_names(self):
        ProjectGroup.objects.create(name="星火计划组", leader=self.member)
        joined = ProjectGroup.objects.create(
            name="星河计划组",
            leader=User.objects.create_user(
                username="identity-leader",
                password="Leader-Password-123!",
            ),
        )
        joined.members.add(self.member)

        labels, groups = self.identities_on_page()

        self.assertEqual(labels, ["项目组联系人", "项目组成员"])
        self.assertIn("星火计划组", groups)
        self.assertIn("星河计划组", groups)

    def test_a_group_member_is_listed_without_being_a_contact(self):
        joined = ProjectGroup.objects.create(
            name="只有成员组",
            leader=User.objects.create_user(
                username="identity-leader",
                password="Leader-Password-123!",
            ),
        )
        joined.members.add(self.member)

        labels, groups = self.identities_on_page()

        self.assertEqual(labels, ["项目组成员"])
        self.assertEqual(groups, ["只有成员组"])

    def test_the_panel_is_read_only_and_sits_below_the_avatar(self):
        self.member.is_reviewer = True
        self.member.save(update_fields=["is_reviewer"])

        response = self.client.get(reverse("accounts:profile"))

        html = response.content.decode()
        self.assertLess(html.index("头像"), html.index("当前身份"), "身份面板在头像之下")
        # 「只读」写在实现里而不是写在页面上：这一段到图册之前没有任何可提交的东西。
        panel = html[html.index("当前身份"): html.index("个人图册")]
        self.assertNotIn("<form", panel)
        self.assertNotIn("<button", panel)


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


