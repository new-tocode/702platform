"""申请类的消息：谁收到、写什么说明、点进哪里去。"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from notices.models import Message
from notices.selectors import message_target_url

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
