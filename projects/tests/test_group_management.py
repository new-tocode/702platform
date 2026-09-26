"""管理页：只有联系人能开，改简介、学院与指导老师。"""

from django.contrib.auth import get_user_model
from django.urls import reverse
from ..models import (
    GroupCreateRequest,
    GroupJoinRequest,
    ProjectAdvisor,
    ProjectGroup,
)
from ..services import GroupManagementError, update_group_info
from .base import ProjectViewTestCase


class GroupManagementViewTests(ProjectViewTestCase):
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
    def test_contact_can_update_description(self):
        self.client.force_login(self.leader)

        response = self.client.post(
            reverse("projects:group_manage", args=(self.group.pk,)),
            {"action": "description", "description": "更新后的介绍。"},
        )

        self.assertEqual(response.status_code, 302)
        self.group.refresh_from_db()
        self.assertEqual(self.group.description, "更新后的介绍。")
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
