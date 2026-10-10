"""入组申请与成员变更：申请→审核、拒绝后重申、移除成员。"""

from django.contrib.auth import get_user_model
from django.urls import reverse
from ..models import (
    GroupCreateRequest,
    GroupJoinRequest,
    ProjectAdvisor,
    ProjectGroup,
)
from ..services import JoinRequestError, apply_to_group
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
    def test_admin_can_apply_to_a_group_they_are_not_in(self):
        """申请不按身份设限：管理员也可以（以个人身份）申请加入别的组。"""
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("projects:group_apply", args=(self.group.pk,)),
            {"message": "以个人身份申请加入。"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            GroupJoinRequest.objects.filter(
                group=self.group,
                applicant=self.admin,
                status=GroupJoinRequest.PENDING,
            ).exists()
        )

    def test_member_cannot_apply_to_their_own_group(self):
        """唯一剩下的限制：已经是这个组的人（含联系人）不能再申请它。

        视图先短路（给一句提示就回列表），服务层再拒一次——直调服务同样拦得住。
        """
        for user in (self.member, self.leader):
            with self.subTest(user=user.username):
                self.client.force_login(user)

                response = self.client.post(
                    reverse("projects:group_apply", args=(self.group.pk,)),
                    {"message": "再申请一次。"},
                )

                self.assertEqual(response.status_code, 302)
        self.assertFalse(GroupJoinRequest.objects.filter(group=self.group).exists())

    def test_service_refuses_an_existing_member(self):
        with self.assertRaises(JoinRequestError):
            apply_to_group(group=self.group, applicant=self.member, message="再来一次")

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
