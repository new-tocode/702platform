"""申请类的消息：谁收到、说明列写什么、点进哪里去。"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from notices.models import Message
from notices.selectors import message_rows, message_target_url

from ..models import GroupCreateRequest, GroupJoinRequest, ProjectGroup
from ..services import (
    apply_to_create_group,
    apply_to_group,
    approve_create_request,
    approve_join_request,
    reject_create_request,
    reject_join_request,
)


User = get_user_model()


class RequestMessageDeliveryTests(TestCase):
    """消息的收件人与幂等：申请给联系人/管理员，结果给申请人。"""

    def setUp(self):
        self.admin = self._user("msg-admin", is_staff=True)
        self.other_admin = self._user("msg-admin-2", is_staff=True)
        self.member = self._user("msg-member")
        self.contact = self._user("msg-contact")
        self.group = ProjectGroup.objects.create(name="消息项目组", leader=self.contact)

    def _user(self, username, **extra):
        user = User.objects.create_user(
            username=username,
            password="Msg-Password-123!",
            **extra,
        )
        user.must_change_password = False
        user.save(update_fields=["must_change_password"])
        return user

    def messages_for(self, user, kind=None):
        messages = Message.objects.filter(recipient=user)
        return messages.filter(kind=kind) if kind else messages

    def test_applying_notifies_the_contact(self):
        join_request = apply_to_group(
            group=self.group, applicant=self.member, message="想加入"
        )

        message = self.messages_for(self.contact, Message.JOIN_REQUEST).get()

        self.assertEqual(message.join_request, join_request)
        self.assertEqual(message.actor, self.member)

    def test_applying_again_does_not_pile_up_messages(self):
        apply_to_group(group=self.group, applicant=self.member, message="想加入")
        apply_to_group(
            group=self.group, applicant=self.member, message="还是想加入"
        )

        self.assertEqual(
            self.messages_for(self.contact, Message.JOIN_REQUEST).count(), 1
        )

    def test_join_approval_notifies_the_applicant(self):
        join_request = apply_to_group(group=self.group, applicant=self.member)

        approve_join_request(join_request=join_request, actor=self.contact)

        message = self.messages_for(self.member, Message.JOIN_RESULT).get()
        self.assertEqual(message.actor, self.contact)

    def test_join_rejection_notifies_the_applicant(self):
        join_request = apply_to_group(group=self.group, applicant=self.member)

        reject_join_request(join_request=join_request, actor=self.contact)

        self.assertTrue(self.messages_for(self.member, Message.JOIN_RESULT).exists())

    def test_applying_to_found_a_group_notifies_every_admin_only(self):
        apply_to_create_group(
            applicant=self.member, name="新组", description="做点新东西。"
        )

        self.assertTrue(self.messages_for(self.admin, Message.CREATE_REQUEST).exists())
        self.assertTrue(
            self.messages_for(self.other_admin, Message.CREATE_REQUEST).exists()
        )
        self.assertFalse(
            self.messages_for(self.contact, Message.CREATE_REQUEST).exists()
        )

    def test_create_approval_notifies_the_applicant(self):
        create_request = apply_to_create_group(
            applicant=self.member, name="新组", description="做点新东西。"
        )

        approve_create_request(create_request=create_request, actor=self.admin)

        message = self.messages_for(self.member, Message.CREATE_RESULT).get()
        self.assertEqual(message.actor, self.admin)

    def test_create_rejection_notifies_the_applicant(self):
        create_request = apply_to_create_group(
            applicant=self.member, name="新组", description="做点新东西。"
        )

        reject_create_request(create_request=create_request, actor=self.admin)

        self.assertTrue(self.messages_for(self.member, Message.CREATE_RESULT).exists())


class RequestMessageRenderingTests(TestCase):
    """消息行与去向：说明文本现取，链接指到能办事的页面。"""

    def setUp(self):
        self.admin = self._user("render-admin", is_staff=True)
        self.member = self._user("render-member")
        self.contact = self._user("render-contact")
        self.group = ProjectGroup.objects.create(name="渲染项目组", leader=self.contact)

    def _user(self, username, **extra):
        user = User.objects.create_user(
            username=username,
            password="Msg-Password-123!",
            **extra,
        )
        user.must_change_password = False
        user.save(update_fields=["must_change_password"])
        return user

    def message_for(self, user, kind):
        return Message.objects.get(recipient=user, kind=kind)

    def test_join_request_points_at_the_group_detail(self):
        apply_to_group(group=self.group, applicant=self.member)

        message = self.message_for(self.contact, Message.JOIN_REQUEST)

        self.assertEqual(
            message_target_url(message),
            reverse("projects:group_detail", args=(self.group.pk,)),
        )

    def test_join_result_reads_the_current_status(self):
        join_request = apply_to_group(group=self.group, applicant=self.member)
        approve_join_request(join_request=join_request, actor=self.contact)

        message = self.message_for(self.member, Message.JOIN_RESULT)

        self.assertEqual(
            message_target_url(message),
            reverse("projects:group_detail", args=(self.group.pk,)),
        )

    def test_create_request_points_at_the_review_queue(self):
        apply_to_create_group(
            applicant=self.member, name="待审新组", description="描述。"
        )

        message = self.message_for(self.admin, Message.CREATE_REQUEST)

        self.assertEqual(message_target_url(message), reverse("reviews:queue"))

    def test_approved_create_result_points_at_the_new_group(self):
        create_request = apply_to_create_group(
            applicant=self.member, name="通过的新组", description="描述。"
        )
        approve_create_request(create_request=create_request, actor=self.admin)
        create_request.refresh_from_db()

        message = self.message_for(self.member, Message.CREATE_RESULT)

        self.assertEqual(
            message_target_url(message),
            reverse("projects:group_detail", args=(create_request.created_group_id,)),
        )

    def test_rejected_create_result_falls_back_to_the_group_list(self):
        create_request = apply_to_create_group(
            applicant=self.member, name="被拒的新组", description="描述。"
        )
        reject_create_request(create_request=create_request, actor=self.admin)

        message = self.message_for(self.member, Message.CREATE_RESULT)

        self.assertEqual(message_target_url(message), reverse("projects:group_list"))


class RequestMessageStatusTests(TestCase):
    """审批类的「说明」格：待办时是待办，处理完连处理人一起报出来。

    这一格与标题一样是**现取**的（``notices.selectors`` 每次装配时读申请行），
    所以别人处理掉之后用不着回填消息——测试也照这条路走。
    """

    def setUp(self):
        self.admin = self._user("status-admin", is_staff=True, full_name="审批管理员")
        self.other_admin = self._user(
            "status-admin-2", is_staff=True, full_name="另一位管理员"
        )
        self.member = self._user("status-member", full_name="申请成员")
        self.contact = self._user("status-contact", full_name="组联系人")
        self.group = ProjectGroup.objects.create(name="状态项目组", leader=self.contact)

    def _user(self, username, full_name="", **extra):
        user = User.objects.create_user(
            username=username,
            password="Msg-Password-123!",
            **extra,
        )
        user.must_change_password = False
        user.save(update_fields=["must_change_password"])
        user.profile.full_name = full_name
        user.profile.save(update_fields=["full_name"])
        return user

    def status_for(self, user, label):
        """那一行的「说明」格——审批类消息在这一格放状态。"""
        return next(
            row.context for row in message_rows(user) if row.type_label == label
        )

    # --- 建组申请（收件人是全体管理员） ---------------------------------

    def test_pending_create_request_reads_as_pending_for_every_admin(self):
        apply_to_create_group(applicant=self.member, name="新组", description="描述。")

        self.assertEqual(self.status_for(self.admin, "建组申请"), "待审核")
        self.assertEqual(self.status_for(self.other_admin, "建组申请"), "待审核")

    def test_approval_tells_the_other_admin_who_settled_it(self):
        create_request = apply_to_create_group(
            applicant=self.member, name="新组", description="描述。"
        )

        approve_create_request(create_request=create_request, actor=self.admin)

        self.assertEqual(
            self.status_for(self.other_admin, "建组申请"),
            "已由 审批管理员 审核通过",
        )

    def test_rejection_tells_the_other_admin_who_settled_it(self):
        create_request = apply_to_create_group(
            applicant=self.member, name="新组", description="描述。"
        )

        reject_create_request(create_request=create_request, actor=self.admin)

        self.assertEqual(
            self.status_for(self.other_admin, "建组申请"), "已被 审批管理员 拒绝"
        )

    def test_create_result_still_reads_as_a_plain_verdict(self):
        # 结果那条的「来自」列就是处理人，状态里不再重复一遍名字。
        create_request = apply_to_create_group(
            applicant=self.member, name="新组", description="描述。"
        )

        approve_create_request(create_request=create_request, actor=self.admin)

        row = next(
            row for row in message_rows(self.member) if row.type_label == "建组结果"
        )
        self.assertEqual(row.actor, "审批管理员")
        self.assertEqual(row.context, "已通过")

    # --- 入组申请（收件人是项目组联系人） -------------------------------

    def test_pending_join_request_reads_as_pending(self):
        apply_to_group(group=self.group, applicant=self.member)

        self.assertEqual(self.status_for(self.contact, "入组申请"), "待你审核")

    def test_join_decision_names_whoever_settled_it(self):
        # 处理人不一定是收件人：换了联系人、或管理员替这个组处理，都要看得出是谁。
        join_request = apply_to_group(group=self.group, applicant=self.member)

        approve_join_request(join_request=join_request, actor=self.admin)

        self.assertEqual(
            self.status_for(self.contact, "入组申请"), "已由 审批管理员 审核通过"
        )

    def test_join_rejection_names_the_contact_when_they_decide(self):
        join_request = apply_to_group(group=self.group, applicant=self.member)

        reject_join_request(join_request=join_request, actor=self.contact)

        self.assertEqual(
            self.status_for(self.contact, "入组申请"), "已被 组联系人 拒绝"
        )

    # --- 老数据 ---------------------------------------------------------

    def test_a_decided_row_without_a_decider_falls_back_to_a_plain_verdict(self):
        # 绕过服务层造出来的行：有结论却没有处理人，不拼出「已由  审核通过」。
        create_request = apply_to_create_group(
            applicant=self.member, name="新组", description="描述。"
        )
        create_request.status = GroupCreateRequest.APPROVED
        create_request.decided_by = None
        create_request.save(update_fields=["status", "decided_by", "updated_at"])

        self.assertEqual(self.status_for(self.admin, "建组申请"), "已通过")


class RequestStatusOnTheMessagePageTests(TestCase):
    """整页走一遍：别人处理掉之后，收件人的「我的消息」上就地写着是谁办的。

    状态是现取的，所以这里不必重建消息、也不必回填——申请行一改，页面跟着改。
    """

    def setUp(self):
        self.applicant = self._user("page-applicant", "申请成员")
        self.decider = self._user("page-decider", "办事管理员", is_staff=True)
        self.bystander = self._user("page-bystander", "旁观管理员", is_staff=True)

    def _user(self, username, full_name, **extra):
        user = User.objects.create_user(
            username=username,
            password="Msg-Password-123!",
            **extra,
        )
        user.must_change_password = False
        user.save(update_fields=["must_change_password"])
        user.profile.full_name = full_name
        user.profile.save(update_fields=["full_name"])
        return user

    def test_the_other_admin_reads_the_outcome_on_the_page(self):
        self.client.force_login(self.applicant)
        self.client.post(
            reverse("projects:group_create_request"),
            {"name": "页面新组", "description": "描述。", "college": "", "advisor_1": ""},
        )
        create_request = GroupCreateRequest.objects.get(applicant=self.applicant)

        self.client.force_login(self.bystander)
        page = self.client.get(reverse("member_notices:internal_list"))
        self.assertContains(page, "待审核")
        self.assertNotContains(page, "已由")

        self.client.force_login(self.decider)
        self.client.post(
            reverse(
                "projects:group_create_decide",
                args=(create_request.pk, "approve"),
            )
        )

        self.client.force_login(self.bystander)
        page = self.client.get(reverse("member_notices:internal_list"))
        self.assertContains(page, "已由 办事管理员 审核通过")
        self.assertNotContains(page, "待审核")

    def test_the_applicant_still_reads_a_plain_verdict(self):
        # 结果那条的「来自」就是办事的人，状态里不再叠一遍名字。
        self.client.force_login(self.applicant)
        self.client.post(
            reverse("projects:group_create_request"),
            {"name": "页面新组", "description": "描述。", "college": "", "advisor_1": ""},
        )
        create_request = GroupCreateRequest.objects.get(applicant=self.applicant)

        self.client.force_login(self.decider)
        self.client.post(
            reverse(
                "projects:group_create_decide",
                args=(create_request.pk, "reject"),
            )
        )

        self.client.force_login(self.applicant)
        page = self.client.get(reverse("member_notices:internal_list"))
        self.assertContains(page, "建组结果")
        self.assertContains(page, "已拒绝")
        self.assertContains(page, "办事管理员")
