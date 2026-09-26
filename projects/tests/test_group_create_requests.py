"""申请创建项目组：成员发起、任一管理员同意即建组。"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from ..models import (
    GroupCreateRequest,
    GroupJoinRequest,
    ProjectAdvisor,
    ProjectGroup,
)


User = get_user_model()


class GroupCreateRequestAcceptanceTests(TestCase):
    """申请创建项目组：任何登录成员可申请，任一管理员同意即通过。"""

    def setUp(self):
        self.admin = self._active_user("create-admin", is_staff=True)
        self.other_admin = self._active_user("create-admin-2", is_staff=True)
        self.member = self._active_user("create-member")
        self.contact = self._active_user("create-contact")
        ProjectGroup.objects.create(name="机器人组", leader=self.contact)

    def _active_user(self, username, **extra):
        user = User.objects.create_user(
            username=username,
            password="Create-Password-123!",
            **extra,
        )
        user.must_change_password = False
        user.save(update_fields=["must_change_password"])
        return user

    def _apply(self, user, **overrides):
        payload = {
            "name": "嵌入式组",
            "description": "做嵌入式方向的竞赛。",
            "college": "",
            "advisor_1": "",
            "advisor_2": "",
            "advisor_3": "",
        }
        payload.update(overrides)
        self.client.force_login(user)
        return self.client.post(reverse("projects:group_create_request"), payload)

    def _decide(self, user, create_request, action):
        self.client.force_login(user)
        return self.client.post(
            reverse(
                "projects:group_create_decide",
                args=(create_request.pk, action),
            ),
            follow=True,
        )

    def test_apply_entry_visible_to_every_logged_in_member(self):
        """不论身份（无组、有组、联系人、管理员）都能看到申请入口。"""
        for user in (self.member, self.contact, self.admin):
            self.client.force_login(user)
            response = self.client.get(reverse("projects:group_list"))
            self.assertContains(response, "申请创建项目组")

    def test_application_needs_only_name_and_description(self):
        response = self._apply(self.member)

        self.assertEqual(response.status_code, 302)
        create_request = GroupCreateRequest.objects.get(applicant=self.member)
        self.assertEqual(create_request.status, GroupCreateRequest.PENDING)
        self.assertEqual(create_request.name, "嵌入式组")
        self.assertEqual(create_request.description, "做嵌入式方向的竞赛。")
        self.assertEqual(create_request.college, "")
        self.assertEqual(create_request.filled_advisor_names, [])

    def test_missing_name_or_description_is_rejected(self):
        response = self._apply(self.member, description="")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(GroupCreateRequest.objects.exists())

    def test_applying_again_refreshes_the_single_pending_request(self):
        self._apply(self.member)
        create_request = GroupCreateRequest.objects.get(applicant=self.member)

        # 再次打开表单时带出已提交的内容，改的是内容而不是重新填一遍。
        self.client.force_login(self.member)
        form_page = self.client.get(reverse("projects:group_create_request"))
        self.assertContains(form_page, 'value="嵌入式组"')

        self._apply(
            self.member,
            name="嵌入式二组",
            college="计算机学院",
            advisor_1="张三",
        )

        self.assertEqual(
            GroupCreateRequest.objects.filter(applicant=self.member).count(),
            1,
        )
        create_request.refresh_from_db()
        self.assertEqual(create_request.name, "嵌入式二组")
        self.assertEqual(create_request.college, "计算机学院")
        self.assertEqual(create_request.filled_advisor_names, ["张三"])

    def test_applicant_sees_pending_state_instead_of_the_apply_button(self):
        self._apply(self.member)

        self.client.force_login(self.member)
        response = self.client.get(reverse("projects:group_list"))

        self.assertContains(response, "创建申请审核中")
        self.assertNotContains(response, "申请创建项目组")

    def test_creation_requests_are_decided_on_the_review_queue_not_here(self):
        """审核入口在管理员的「评审」页；这一页只有申请按钮，没有待审列表。"""
        self._apply(self.member, college="计算机学院", advisor_1="张三")

        self.client.force_login(self.admin)
        response = self.client.get(reverse("projects:group_list"))

        self.assertContains(response, "申请创建项目组")
        self.assertNotContains(response, "创建项目组申请")
        self.assertNotContains(response, "嵌入式组")

    def test_anonymous_cannot_open_the_application_form(self):
        response = self.client.get(reverse("projects:group_create_request"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def test_any_administrator_approval_founds_the_group(self):
        self._apply(
            self.member,
            college="计算机学院",
            advisor_1="张三",
            advisor_2="李四",
        )
        create_request = GroupCreateRequest.objects.get(applicant=self.member)

        response = self._decide(self.admin, create_request, "approve")

        self.assertEqual(response.status_code, 200)
        create_request.refresh_from_db()
        group = create_request.created_group
        self.assertIsNotNone(group)
        self.assertEqual(create_request.status, GroupCreateRequest.APPROVED)
        self.assertEqual(create_request.decided_by, self.admin)
        self.assertEqual(group.name, "嵌入式组")
        self.assertEqual(group.leader, self.member)
        self.assertIn(self.member, group.members.all())
        self.assertEqual(group.description, "做嵌入式方向的竞赛。")
        self.assertEqual(group.college, "计算机学院")
        self.assertEqual(
            [(advisor.sort_order, advisor.name) for advisor in group.advisors.all()],
            [(0, "张三"), (1, "李四")],
        )

        # 通过后该组即刻出现在项目组列表中，且不再有待审申请。
        self.client.force_login(self.member)
        listing = self.client.get(reverse("projects:group_list"))
        self.assertContains(listing, "嵌入式组")
        self.assertNotContains(listing, "创建申请审核中")

    def test_first_approval_settles_it_for_the_other_administrators(self):
        self._apply(self.member)
        create_request = GroupCreateRequest.objects.get(applicant=self.member)

        self._decide(self.admin, create_request, "approve")
        second = self._decide(self.other_admin, create_request, "approve")

        self.assertContains(second, "该申请已被处理")
        self.assertEqual(ProjectGroup.objects.filter(name="嵌入式组").count(), 1)

    def test_rejected_applicant_can_apply_again(self):
        self._apply(self.member)
        create_request = GroupCreateRequest.objects.get(applicant=self.member)

        response = self._decide(self.admin, create_request, "reject")

        self.assertEqual(response.status_code, 200)
        create_request.refresh_from_db()
        self.assertEqual(create_request.status, GroupCreateRequest.REJECTED)
        self.assertEqual(create_request.decided_by, self.admin)
        self.assertIsNone(create_request.created_group)
        self.assertFalse(ProjectGroup.objects.filter(name="嵌入式组").exists())

        self._apply(self.member, name="嵌入式组（第二次）")
        self.assertEqual(
            GroupCreateRequest.objects.filter(
                applicant=self.member,
                status=GroupCreateRequest.PENDING,
            ).count(),
            1,
        )

    def test_non_administrator_cannot_decide(self):
        self._apply(self.member)
        create_request = GroupCreateRequest.objects.get(applicant=self.member)

        response = self._decide(self.contact, create_request, "approve")

        self.assertEqual(response.status_code, 403)
        create_request.refresh_from_db()
        self.assertEqual(create_request.status, GroupCreateRequest.PENDING)
        self.assertFalse(ProjectGroup.objects.filter(name="嵌入式组").exists())
