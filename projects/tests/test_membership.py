"""入组申请与成员变更：申请→审核、拒绝后重申、移除成员。"""

from django.contrib.auth import get_user_model
from django.urls import reverse
from ..models import (
    GroupCreateRequest,
    GroupJoinRequest,
    ProjectAdvisor,
    ProjectGroup,
)
from .base import ProjectViewTestCase


class MembershipViewTests(ProjectViewTestCase):
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
