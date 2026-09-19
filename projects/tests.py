"""Acceptance tests for project-group membership and visibility."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import (
    GroupCreateRequest,
    GroupJoinRequest,
    ProjectAdvisor,
    ProjectGroup,
)
from .services import GroupManagementError, update_group_info


User = get_user_model()


class ProjectGroupAcceptanceTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="project-admin",
            password="Admin-Password-123!",
        )
        self.leader = User.objects.create_user(
            username="project-leader",
            password="Leader-Password-123!",
        )
        self.leader.must_change_password = False
        self.leader.save(update_fields=["must_change_password"])
        self.member = User.objects.create_user(
            username="project-member",
            password="Member-Password-123!",
        )
        self.member.must_change_password = False
        self.member.save(update_fields=["must_change_password"])
        self.no_group_user = User.objects.create_user(
            username="project-outsider",
            password="Outsider-Password-123!",
        )
        self.no_group_user.must_change_password = False
        self.no_group_user.save(update_fields=["must_change_password"])
        self.other_leader = User.objects.create_user(
            username="other-leader",
            password="Other-Leader-123!",
        )
        self.other_leader.must_change_password = False
        self.other_leader.save(update_fields=["must_change_password"])

        self.group = ProjectGroup.objects.create(
            name="机器人组",
            leader=self.leader,
            description="负责机器人竞赛。",
        )
        self.group.members.add(self.member)
        self.other_group = ProjectGroup.objects.create(
            name="算法组",
            leader=self.other_leader,
        )

    def test_group_leader_is_automatically_a_group_member(self):
        self.assertIn(self.leader, self.group.members.all())
        self.assertIn(self.member, self.group.members.all())

    def test_group_member_sees_only_their_own_group(self):
        self.client.force_login(self.member)

        response = self.client.get(reverse("projects:group_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.group.name)
        self.assertNotContains(response, self.other_group.name)

    def test_user_without_group_sees_all_groups_to_apply(self):
        self.client.force_login(self.no_group_user)

        response = self.client.get(reverse("projects:group_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.group.name)
        self.assertContains(response, self.other_group.name)
        self.assertContains(response, "申请加入")

    def test_contact_sees_all_groups_with_manage_link(self):
        self.client.force_login(self.leader)

        response = self.client.get(reverse("projects:group_list"))

        self.assertContains(response, self.group.name)
        self.assertContains(response, self.other_group.name)
        self.assertContains(
            response,
            reverse("projects:group_manage", args=(self.group.pk,)),
        )

    def test_anonymous_cannot_view_project_groups(self):
        response = self.client.get(reverse("projects:group_list"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def test_admin_can_manage_project_groups_and_regular_member_cannot(self):
        self.client.force_login(self.admin)
        admin_response = self.client.get("/admin/projects/projectgroup/")
        self.assertEqual(admin_response.status_code, 200)

        self.client.force_login(self.member)
        member_response = self.client.get("/admin/projects/projectgroup/")
        self.assertEqual(member_response.status_code, 302)

    def test_admin_can_create_group_and_leader_is_kept_as_member(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("admin:projects_projectgroup_add"),
            {
                "name": "新算法组",
                "leader": self.leader.pk,
                "members": [self.member.pk],
                "description": "算法竞赛项目组。",
                "college": "计算机学院",
                # 指导老师内联的表单集管理表单；缺了它整张表单会被判为无效。
                "advisors-TOTAL_FORMS": "1",
                "advisors-INITIAL_FORMS": "0",
                "advisors-MIN_NUM_FORMS": "0",
                "advisors-MAX_NUM_FORMS": "3",
                "advisors-0-sort_order": "0",
                "advisors-0-name": "张三",
                "_save": "保存",
            },
        )

        self.assertEqual(response.status_code, 302)
        group = ProjectGroup.objects.get(name="新算法组")
        self.assertIn(self.leader, group.members.all())
        self.assertIn(self.member, group.members.all())
        self.assertEqual(group.college, "计算机学院")
        self.assertEqual(group.advisor_names, "张三")

    def test_member_applies_and_contact_approves(self):
        self.client.force_login(self.no_group_user)
        apply_response = self.client.post(
            reverse("projects:group_apply", args=(self.group.pk,)),
            {"message": "希望加入机器人组。"},
        )

        self.assertEqual(apply_response.status_code, 302)
        join_request = GroupJoinRequest.objects.get(
            group=self.group,
            applicant=self.no_group_user,
        )
        self.assertEqual(join_request.status, GroupJoinRequest.PENDING)

        self.client.force_login(self.leader)
        decide_response = self.client.post(
            reverse(
                "projects:group_request_decide",
                args=(self.group.pk, join_request.pk, "approve"),
            )
        )

        self.assertEqual(decide_response.status_code, 302)
        join_request.refresh_from_db()
        self.assertEqual(join_request.status, GroupJoinRequest.APPROVED)
        self.assertEqual(join_request.decided_by, self.leader)
        self.assertIn(self.no_group_user, self.group.members.all())

    def test_duplicate_pending_application_is_rejected(self):
        self.client.force_login(self.no_group_user)
        url = reverse("projects:group_apply", args=(self.group.pk,))

        self.client.post(url, {"message": "第一次申请。"})
        self.client.post(url, {"message": "重复申请。"})

        self.assertEqual(
            GroupJoinRequest.objects.filter(
                group=self.group,
                applicant=self.no_group_user,
                status=GroupJoinRequest.PENDING,
            ).count(),
            1,
        )

    def test_rejected_applicant_can_apply_again(self):
        self.client.force_login(self.no_group_user)
        self.client.post(
            reverse("projects:group_apply", args=(self.group.pk,)),
            {"message": "第一次申请。"},
        )
        join_request = GroupJoinRequest.objects.get(
            group=self.group,
            applicant=self.no_group_user,
        )

        self.client.force_login(self.leader)
        self.client.post(
            reverse(
                "projects:group_request_decide",
                args=(self.group.pk, join_request.pk, "reject"),
            )
        )

        self.client.force_login(self.no_group_user)
        response = self.client.post(
            reverse("projects:group_apply", args=(self.group.pk,)),
            {"message": "再次申请。"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            GroupJoinRequest.objects.filter(
                group=self.group,
                applicant=self.no_group_user,
                status=GroupJoinRequest.PENDING,
            ).count(),
            1,
        )

    def test_contact_can_remove_member(self):
        self.client.force_login(self.leader)

        response = self.client.post(
            reverse(
                "projects:group_member_remove",
                args=(self.group.pk, self.member.pk),
            )
        )

        self.assertEqual(response.status_code, 302)
        self.assertNotIn(self.member, self.group.members.all())

    def test_contact_cannot_be_removed(self):
        self.client.force_login(self.leader)

        response = self.client.post(
            reverse(
                "projects:group_member_remove",
                args=(self.group.pk, self.leader.pk),
            )
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(self.leader, self.group.members.all())

    def test_contact_transfer_keeps_former_contact_as_member(self):
        self.client.force_login(self.leader)

        response = self.client.post(
            reverse("projects:group_manage", args=(self.group.pk,)),
            {"action": "transfer", "new_contact": self.member.pk},
        )

        self.assertEqual(response.status_code, 302)
        self.group.refresh_from_db()
        self.assertEqual(self.group.leader, self.member)
        self.assertIn(self.leader, self.group.members.all())

    def test_contact_can_update_description(self):
        self.client.force_login(self.leader)

        response = self.client.post(
            reverse("projects:group_manage", args=(self.group.pk,)),
            {"action": "description", "description": "更新后的介绍。"},
        )

        self.assertEqual(response.status_code, 302)
        self.group.refresh_from_db()
        self.assertEqual(self.group.description, "更新后的介绍。")

    def test_non_contact_cannot_open_manage_page(self):
        self.client.force_login(self.member)

        response = self.client.get(
            reverse("projects:group_manage", args=(self.group.pk,))
        )

        self.assertEqual(response.status_code, 403)

    def test_contact_renders_manage_page_with_all_sections(self):
        """管理页必须真的渲染得出来：此前没有任何测试 GET 过它。"""
        self.client.force_login(self.leader)

        response = self.client.get(
            reverse("projects:group_manage", args=(self.group.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "管理「机器人组」")
        for section in (
            "入组申请",
            "成员",
            "项目组介绍",
            "学院与指导老师",
            "项目书",
            "提交审核",
            "转让联系人",
        ):
            self.assertContains(response, section)

    def test_manage_page_lists_pending_request_and_real_proposal_file(self):
        GroupJoinRequest.objects.create(
            group=self.group,
            applicant=self.no_group_user,
            message="希望加入机器人组。",
        )
        self.group.proposal = "project_proposals/2026/09/开题报告.docx"
        self.group.save(update_fields=["proposal"])
        self.client.force_login(self.leader)

        response = self.client.get(
            reverse("projects:group_manage", args=(self.group.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.no_group_user.username)
        self.assertContains(response, "希望加入机器人组。")
        # 角标与文件名取自真实路径，不是写死的占位符
        self.assertContains(response, "开题报告.docx")
        self.assertContains(response, "DOCX")
        self.assertNotContains(response, ">DOC</span>")

    def test_group_detail_derives_extension_from_proposal_filename(self):
        self.group.proposal = "project_proposals/2026/09/开题报告.pdf"
        self.group.save(update_fields=["proposal"])
        self.client.force_login(self.leader)

        response = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "开题报告.pdf")
        self.assertContains(response, "PDF")

    def test_contact_can_update_college_and_advisors(self):
        self.client.force_login(self.leader)

        response = self.client.post(
            reverse("projects:group_manage", args=(self.group.pk,)),
            {
                "action": "info",
                "college": "计算机学院",
                "advisor_1": "张三",
                "advisor_2": "李四",
                "advisor_3": "王五",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.group.refresh_from_db()
        self.assertEqual(self.group.college, "计算机学院")
        self.assertEqual(
            list(self.group.advisors.values_list("sort_order", "name")),
            [(0, "张三"), (1, "李四"), (2, "王五")],
        )

    def test_cleared_advisor_slot_closes_the_gap(self):
        """空槽位不占位：后面的老师补上来，且不会撞上槽位唯一约束。"""
        for slot, name in enumerate(("张三", "李四", "王五")):
            ProjectAdvisor.objects.create(group=self.group, name=name, sort_order=slot)
        self.client.force_login(self.leader)

        self.client.post(
            reverse("projects:group_manage", args=(self.group.pk,)),
            {
                "action": "info",
                "college": "",
                "advisor_1": "张三",
                "advisor_2": "",
                "advisor_3": "王五",
            },
        )

        self.assertEqual(
            list(self.group.advisors.values_list("sort_order", "name")),
            [(0, "张三"), (1, "王五")],
        )

    def test_advisor_cap_cannot_be_exceeded_through_the_service(self):
        """表单只给三个槽位；服务层这道关挡住绕过表单的调用。"""
        with self.assertRaises(GroupManagementError):
            update_group_info(
                group=self.group,
                college="计算机学院",
                advisor_names=["甲", "乙", "丙", "丁"],
                actor=self.leader,
            )

        self.group.refresh_from_db()
        self.assertEqual(self.group.advisors.count(), 0)
        self.assertEqual(self.group.college, "")

    def test_group_detail_and_list_show_college_and_advisors(self):
        self.group.college = "计算机学院"
        self.group.save(update_fields=["college"])
        ProjectAdvisor.objects.create(group=self.group, name="张三", sort_order=0)
        ProjectAdvisor.objects.create(group=self.group, name="李四", sort_order=1)
        self.client.force_login(self.leader)

        detail = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "计算机学院")
        self.assertContains(detail, "张三、李四")

        listing = self.client.get(reverse("projects:group_list"))
        self.assertEqual(listing.status_code, 200)
        self.assertContains(listing, "计算机学院")
        self.assertContains(listing, "张三、李四")

    def test_group_without_advisors_renders_placeholder_in_detail(self):
        """没填时详情页仍要渲染得出来，用 — 占位而不是留空。"""
        self.client.force_login(self.leader)

        response = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "项目组信息")
        self.assertContains(response, "指导老师")
        self.assertNotContains(response, ">DOC</span>")


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

    def test_administrator_sees_pending_requests_on_the_project_page(self):
        self._apply(self.member, college="计算机学院", advisor_1="张三")

        self.client.force_login(self.admin)
        response = self.client.get(reverse("projects:group_list"))

        self.assertContains(response, "创建项目组申请")
        self.assertContains(response, "嵌入式组")
        self.assertContains(response, "计算机学院")
        self.assertContains(response, "张三")
        self.assertContains(response, "同意")

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
