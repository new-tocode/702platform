"""Acceptance tests for project-group membership and visibility."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import ProjectGroup


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
        self.group = ProjectGroup.objects.create(
            name="机器人组",
            leader=self.leader,
            description="负责机器人竞赛。",
        )
        self.group.members.add(self.member)

    def test_group_leader_is_automatically_a_group_member(self):
        self.assertIn(self.leader, self.group.members.all())
        self.assertIn(self.member, self.group.members.all())

    def test_authenticated_member_can_view_all_project_groups(self):
        self.client.force_login(self.member)

        response = self.client.get(reverse("projects:group_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.group.name)
        self.assertContains(response, "负责机器人竞赛")
        self.assertContains(response, "project-leader")
        self.assertContains(response, "project-member")

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
                "name": "算法组",
                "leader": self.leader.pk,
                "members": [self.member.pk],
                "description": "算法竞赛项目组。",
                "_save": "保存",
            },
        )

        self.assertEqual(response.status_code, 302)
        group = ProjectGroup.objects.get(name="算法组")
        self.assertIn(self.leader, group.members.all())
        self.assertIn(self.member, group.members.all())
