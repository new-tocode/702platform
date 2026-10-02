"""评审待办的去向：「我的消息」负责提醒，评审页只负责列出任务。

分配（初审、评审、改派）时给持有人写一条消息；任务交掉、被释放或被改派走就
撤掉——消息只负责「有事等你」，历史归评审页（已完成／已释放都在那里列着）。
结论落定时给项目组联系人写一条结果。登录 flash 与成员中心待办卡片已经撤销：
同一个数字不再有两处口径。
"""

from django.urls import reverse

from notices.models import Message

from ..models import ReviewTask
from ..services import (
    override_review,
    pending_task_summary,
    reassign_task,
    submit_verdict,
)
from .base import (
    ONE_REVIEWER_TYPE,
    ReviewTestCase,
)
from .factories import (
    make_group,
    make_preliminary_reviewer,
    make_reviewer,
    make_super_reviewer,
    make_user,
)


class ReviewTaskMessageTests(ReviewTestCase):
    """任务消息：分配时写、交掉/释放/改派时撤，结论给联系人。"""

    round_type = ONE_REVIEWER_TYPE

    def setUp(self):
        self.contact = make_user("remind-contact")
        self.reviewer = make_reviewer("remind-reviewer")
        self.preliminary = make_preliminary_reviewer("remind-preliminary")
        self.member = make_user("remind-member")
        self.group = make_group("提醒项目组", leader=self.contact)

    def messages_for(self, user, kind=None):
        messages = Message.objects.filter(recipient=user)
        return messages.filter(kind=kind) if kind else messages

    def test_submitting_writes_a_preliminary_task_message(self):
        submission = self._open_round()

        message = self.messages_for(self.preliminary, Message.REVIEW_PRELIMINARY).get()

        self.assertEqual(message.submission, submission)
        self.assertFalse(message.is_read)

    def test_preliminary_approval_clears_it_and_writes_reviewer_messages(self):
        submission = self._submit()

        self.assertFalse(self.messages_for(self.preliminary).exists())
        message = self.messages_for(self.reviewer, Message.REVIEW).get()
        self.assertEqual(message.submission, submission)

    def test_preliminary_rejection_clears_the_task_and_notifies_the_contact(self):
        submission = self._open_round()

        self._pass_preliminary(
            submission, decision=ReviewTask.REVISE, comment="请补充数据。"
        )

        self.assertFalse(self.messages_for(self.preliminary).exists())
        result = self.messages_for(self.contact, Message.REVIEW_RESULT).get()
        self.assertEqual(result.submission, submission)

    def test_completing_a_review_clears_its_message(self):
        submission = self._submit()
        assignment = self.review_tasks(submission).get()

        submit_verdict(
            task=assignment,
            reviewer=self.reviewer,
            decision=ReviewTask.APPROVE,
            comment="同意。",
        )

        self.assertFalse(self.messages_for(self.reviewer).exists())

    def test_approved_round_writes_one_result_message_to_the_contact(self):
        submission = self._submit()

        self._approve_round(submission)

        results = self.messages_for(self.contact, Message.REVIEW_RESULT)
        self.assertEqual(results.count(), 1)
        self.assertEqual(results.get().submission, submission)

    def test_reassigning_moves_the_message_to_the_new_reviewer(self):
        submission = self._submit()
        task = self.review_tasks(submission).get()
        newcomer = make_reviewer("remind-newcomer")
        admin = make_user("remind-admin", is_staff=True)

        reassign_task(task=task, new_reviewer=newcomer, actor=admin)

        self.assertFalse(self.messages_for(self.reviewer).exists())
        self.assertTrue(self.messages_for(newcomer, Message.REVIEW).exists())

    def test_override_clears_pending_messages_and_writes_the_result(self):
        submission = self._submit()
        super_reviewer = make_super_reviewer("remind-super")

        override_review(
            submission=submission,
            super_reviewer=super_reviewer,
            decision=ReviewTask.APPROVE,
            comment="直接通过。",
        )

        self.assertFalse(self.messages_for(self.reviewer).exists())
        self.assertTrue(self.messages_for(self.contact, Message.REVIEW_RESULT).exists())


class ReviewMessageDeliveryTests(ReviewTestCase):
    """消息落到页面上：我的消息列得出来，成员中心按未读提醒，旧的两处已撤。"""

    round_type = ONE_REVIEWER_TYPE

    def setUp(self):
        self.contact = make_user("remind-page-contact")
        self.reviewer = make_reviewer("remind-page-reviewer")
        self.preliminary = make_preliminary_reviewer("remind-page-preliminary")
        self.member = make_user("remind-page-member")
        self.group = make_group("提醒页项目组", leader=self.contact)

    def test_preliminary_reviewer_sees_the_task_in_my_messages(self):
        self._open_round()
        self.client.force_login(self.preliminary)

        response = self.client.get(reverse("member_notices:internal_list"))

        self.assertContains(response, "评审")
        self.assertContains(response, "待初审")
        self.assertContains(response, "提醒页项目组（第 1 轮）")

    def test_member_home_reminds_through_the_message_count(self):
        self._open_round()
        self.client.force_login(self.preliminary)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertContains(response, "1 条未读消息")
        # 旧的待办卡片已撤：这个措辞不再出现。
        self.assertNotContains(response, "份项目书待你初审")
        self.assertNotContains(response, "点击前往处理")

    def test_login_no_longer_flashes_a_review_nudge(self):
        self._open_round()

        response = self.client.post(
            reverse("accounts:login"),
            {"username": self.preliminary.username, "password": "Password-123!"},
            follow=True,
        )

        self.assertNotContains(response, "份项目书待初审")
        self.assertNotContains(response, "请前往「评审」处理")

    def test_queue_page_still_lists_the_task(self):
        """评审页只负责列出任务——提醒撤了，列表在。"""
        self._open_round()
        self.client.force_login(self.preliminary)

        response = self.client.get(reverse("reviews:queue"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "提醒页项目组")

    def test_pending_count_still_serves_the_queue_page(self):
        """pending_task_summary 的计数口径没变，队列页仍从这里取数。"""
        submission = self._open_round()

        self.assertEqual(pending_task_summary(self.preliminary).preliminary, 1)

        ReviewTask.objects.filter(submission=submission).update(
            status=ReviewTask.RELEASED
        )

        self.assertEqual(pending_task_summary(self.preliminary).preliminary, 0)

    def test_marking_the_message_read_clears_the_member_home_reminder(self):
        from notices.services import mark_all_read

        self._open_round()
        self.client.force_login(self.preliminary)

        mark_all_read(user=self.preliminary)

        response = self.client.get(reverse("accounts:member_home"))
        self.assertNotContains(response, "未读消息")
