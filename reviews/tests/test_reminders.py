"""待办提醒：登录时的一条提醒，与成员中心顶部的常驻卡片。

初审与评审两种任务分开报数——它们是两件事，一个数字说明不了另一个。
"""

from django.urls import reverse

from ..models import ReviewTask
from ..services import (
    pending_task_summary,
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
    make_user,
)


class ReviewReminderTests(ReviewTestCase):
    #: 只开一人的轮次：这位评审人是否被抽中就是待办数字的全部。
    round_type = ONE_REVIEWER_TYPE

    """Unfinished reviews are surfaced twice: right after login, and on the member centre."""

    def setUp(self):
        self.contact = make_user("remind-contact")
        self.reviewer = make_reviewer("remind-reviewer")
        self.preliminary = make_preliminary_reviewer("remind-preliminary")
        self.member = make_user("remind-member")
        self.group = make_group("提醒项目组", leader=self.contact)
    """Unfinished reviews are surfaced twice: right after login, and on the member centre."""

    def _login(self, username):
        return self.client.post(
            reverse("accounts:login"),
            {"username": username, "password": "Password-123!"},
            follow=True,
        )

    # --- the count -----------------------------------------------------------

    def test_count_only_covers_pending_tasks(self):
        submission = self._submit()
        self.assertEqual(pending_task_summary(self.reviewer).review, 1)

        submit_verdict(
            task=self.review_tasks(submission).get(),
            reviewer=self.reviewer,
            decision=ReviewTask.APPROVE,
            comment="同意。",
        )

        self.assertEqual(pending_task_summary(self.reviewer).review, 0)

    def test_count_accumulates_across_groups(self):
        """同一名评审人可能同时持有来自不同项目组的待评审任务。"""
        other_group = make_group("提醒项目组二", leader=self.contact)

        self._submit()
        self._submit(group=other_group)

        self.assertEqual(pending_task_summary(self.reviewer).review, 2)

    def test_preliminary_count_only_covers_pending_preliminary_tasks(self):
        submission = self._open_round()
        self.assertEqual(pending_task_summary(self.preliminary).preliminary, 1)

        self.assertIsNotNone(submission.preliminary_task)
        ReviewTask.objects.filter(submission=submission).update(
            status=ReviewTask.RELEASED
        )

        self.assertEqual(pending_task_summary(self.preliminary).preliminary, 0)

    # --- the login nudge -----------------------------------------------------

    def test_login_reminds_a_reviewer_holding_pending_tasks(self):
        self._submit()

        response = self._login(self.reviewer.username)

        self.assertContains(response, "1 份项目书待评审")

    def test_login_stays_quiet_without_pending_tasks(self):
        response = self._login(self.reviewer.username)

        self.assertNotContains(response, "份项目书待评审")

    def test_login_stays_quiet_after_the_qualification_is_revoked(self):
        """Reminding someone who can no longer open the queue would mislead them."""
        self._submit()
        self.reviewer.is_reviewer = False
        self.reviewer.save(update_fields=["is_reviewer"])

        response = self._login(self.reviewer.username)

        self.assertNotContains(response, "份项目书待评审")

    def test_login_stays_quiet_for_a_plain_member(self):
        self._submit()

        response = self._login(self.member.username)

        self.assertNotContains(response, "份项目书待评审")

    def test_login_reminds_a_preliminary_reviewer_too(self):
        self._open_round()

        response = self._login(self.preliminary.username)

        self.assertContains(response, "1 份项目书待初审")

    def test_login_names_both_kinds_of_pending_task(self):
        """同一个人两种任务都有时，提醒要把两个数字分开说。"""
        both = make_user("remind-both", is_reviewer=True, is_preliminary_reviewer=True)
        other_group = make_group("提醒项目组二", leader=self.contact)
        review_round = self._submit()
        preliminary_round = self._open_round(group=other_group)
        # 把两条任务都记到这个账号名下：两种资格都具备的人，手上有两种任务。
        # 评审任务只挪一条——一人一轮一席，多挪一条就会撞唯一约束。
        review_task = ReviewTask.objects.filter(
            submission=review_round, stage=ReviewTask.REVIEW
        ).first()
        review_task.reviewer = both
        review_task.save(update_fields=["reviewer"])
        ReviewTask.objects.filter(submission=preliminary_round).update(reviewer=both)

        response = self._login("remind-both")

        self.assertContains(response, "1 份项目书待初审")
        self.assertContains(response, "1 份项目书待评审")

    # --- the member-centre todo card -----------------------------------------

    def test_member_home_shows_a_todo_card_with_the_count(self):
        self._submit()
        self.client.force_login(self.reviewer)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertEqual(response.context["pending"].review, 1)
        self.assertContains(response, "份项目书待你评审")
        self.assertContains(response, '<span class="n">1</span>')

    def test_member_home_shows_no_todo_card_when_nothing_is_pending(self):
        self.client.force_login(self.reviewer)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertEqual(response.context["pending"].review, 0)
        self.assertNotContains(response, "份项目书待你评审")

    def test_member_home_counts_preliminary_tasks_of_their_own(self):
        self._open_round()
        self.client.force_login(self.preliminary)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertEqual(response.context["pending"].preliminary, 1)
        self.assertEqual(response.context["pending"].review, 0)
        self.assertContains(response, "份项目书待你初审")
        self.assertContains(response, '<span class="n">1</span>')

    def test_member_home_shows_no_todo_card_for_non_reviewers(self):
        self.client.force_login(self.member)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertNotIn("pending", response.context)
        self.assertNotContains(response, "份项目书待你评审")


