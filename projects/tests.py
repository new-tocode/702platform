"""Acceptance tests for project-group membership and visibility."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import GroupJoinRequest, ProjectGroup


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
                "_save": "保存",
            },
        )

        self.assertEqual(response.status_code, 302)
        group = ProjectGroup.objects.get(name="新算法组")
        self.assertIn(self.leader, group.members.all())
        self.assertIn(self.member, group.members.all())

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
