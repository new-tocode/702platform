"""评审请假：窗口内不被抽中，到点自动恢复。

「恢复」不是谁去翻一个标志位，而是窗口的 ends_at 过去了——所以这里的断言围着
时间转：起止与过期即恢复。窗口同时挡住初审与评审两种抽取，因为它描述的是这个人
有没有空，与平台准备派给他哪种任务无关。
"""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog

from ..forms import ReviewerLeaveForm
from ..models import (
    REVIEW_TYPE_INNOVATION_MIDTERM,
    ReviewerLeave,
)
from ..services import (
    ReviewError,
    clear_reviewer_leave,
    set_reviewer_leave,
)
from .base import (
    ONE_REVIEWER_TYPE,
    ReviewTestCase,
)
from .factories import (
    make_admin,
    make_group,
    make_preliminary_reviewer,
    make_reviewer,
    make_user,
)


class ReviewerLeaveTests(ReviewTestCase):
    #: 只开一人的轮次：候选人数少，抽签结果才写得死。
    round_type = ONE_REVIEWER_TYPE

    """Review leave suspends new review tasks for a window, then self-restores.

    Eligibility is never stored as a flag — it is derived from the window — so
    「恢复」不需要任何定时任务。These tests pin that down.
    """

    def setUp(self):
        self.admin = make_admin("leave-admin")
        self.contact = make_user("leave-contact")
        self.reviewer = make_reviewer("leave-reviewer")
        self.preliminary = make_preliminary_reviewer("leave-preliminary")
        self.member = make_user("leave-member")
        self.group = make_group("请假项目组", leader=self.contact)
    """Review leave suspends new review requests for a window, then self-restores.

    Eligibility is never stored as a flag — it is derived from the window — so
    "恢复" needs no scheduled job. These tests pin that down.
    """

    def _leave(self, *, reviewer=None, starts_in=-1, ends_in=7, reason=""):
        """Create a leave window relative to now, in days."""
        now = timezone.now()
        return ReviewerLeave.objects.create(
            reviewer=reviewer or self.reviewer,
            starts_at=now + timedelta(days=starts_in),
            ends_at=now + timedelta(days=ends_in),
            reason=reason,
        )

    def _draw_one(self):
        """Submit a single-reviewer round; returns the drawn reviewer."""
        submission = self._open_round()
        self._pass_preliminary(submission)
        return self.review_tasks(submission).get().reviewer

    # --- the window itself ---------------------------------------------------

    def test_state_tracks_the_window(self):
        self.assertEqual(
            self._leave(starts_in=1, ends_in=7).state, ReviewerLeave.LEAVE_UPCOMING
        )
        self.assertEqual(
            self._leave(starts_in=-1, ends_in=1).state, ReviewerLeave.LEAVE_ACTIVE
        )
        self.assertEqual(
            self._leave(starts_in=-7, ends_in=-1).state, ReviewerLeave.LEAVE_ENDED
        )

    # --- effect on reviewer draws -------------------------------------------

    def test_reviewer_on_leave_is_not_drawn(self):
        other = make_reviewer("leave-reviewer-two")
        self._leave(starts_in=-1, ends_in=7)

        self.assertEqual(self._draw_one(), other)

    def test_expired_leave_restores_eligibility(self):
        """No job runs at ends_at — the reviewer is simply eligible again."""
        other = make_reviewer("leave-reviewer-two")
        self._leave(starts_in=-7, ends_in=-1)
        self._leave(reviewer=other, starts_in=-1, ends_in=7)

        self.assertEqual(self._draw_one(), self.reviewer)

    def test_leave_that_has_not_started_does_not_exclude_yet(self):
        other = make_reviewer("leave-reviewer-two")
        self._leave(starts_in=1, ends_in=7)
        self._leave(reviewer=other, starts_in=-1, ends_in=7)

        self.assertEqual(self._draw_one(), self.reviewer)

    def test_preliminary_reviewer_on_leave_is_not_drawn_for_preliminary(self):
        """请假窗口对初审同样生效：它说的是这个人现在不在，与任务种类无关。"""
        other = make_preliminary_reviewer("leave-preliminary-two")
        self._leave(reviewer=self.preliminary, starts_in=-1, ends_in=7)

        drawn = self._open_round().preliminary_task.reviewer

        self.assertEqual(drawn, other)

    def test_shortage_message_mentions_how_many_are_on_leave(self):
        self._leave(starts_in=-1, ends_in=7)

        with self.assertRaises(ReviewError) as caught:
            self._open_round(review_type=REVIEW_TYPE_INNOVATION_MIDTERM)

        self.assertIn("另有 1 人请假", str(caught.exception))

    def test_the_leave_note_counts_only_accounts_holding_the_qualification(self):
        """提示里的「另有 N 人请假」只算得上的人：初审人请假与评审人缺口无关。"""
        # 另留一位初审人在岗，送审才走得到评审人这一步。
        make_preliminary_reviewer("leave-preliminary-two")
        self._leave(reviewer=self.preliminary, starts_in=-1, ends_in=7)

        with self.assertRaises(ReviewError) as caught:
            self._open_round(review_type=REVIEW_TYPE_INNOVATION_MIDTERM)

        self.assertIn("评审人不足", str(caught.exception))
        self.assertNotIn("请假", str(caught.exception))

    def test_clearing_leave_restores_immediately(self):
        other = make_reviewer("leave-reviewer-two")
        self._leave(starts_in=-1, ends_in=7)
        self._leave(reviewer=other, starts_in=-1, ends_in=7)
        with self.assertRaises(ReviewError):
            self._open_round()

        clear_reviewer_leave(reviewer=self.reviewer, actor=self.reviewer)

        self.assertEqual(self._draw_one(), self.reviewer)

    # --- registering and clearing -------------------------------------------

    def test_registering_twice_edits_the_same_window(self):
        now = timezone.now()
        set_reviewer_leave(
            reviewer=self.reviewer,
            starts_at=now,
            ends_at=now + timedelta(days=3),
            actor=self.reviewer,
        )
        leave = set_reviewer_leave(
            reviewer=self.reviewer,
            starts_at=now,
            ends_at=now + timedelta(days=10),
            actor=self.reviewer,
        )

        self.assertEqual(ReviewerLeave.objects.filter(reviewer=self.reviewer).count(), 1)
        self.assertEqual(leave.ends_at, now + timedelta(days=10))

    def test_leave_must_end_in_the_future(self):
        now = timezone.now()

        with self.assertRaises(ReviewError):
            set_reviewer_leave(
                reviewer=self.reviewer,
                starts_at=now - timedelta(days=2),
                ends_at=now - timedelta(days=1),
                actor=self.reviewer,
            )

    def test_leave_must_end_after_it_starts(self):
        now = timezone.now()

        with self.assertRaises(ReviewError):
            set_reviewer_leave(
                reviewer=self.reviewer,
                starts_at=now + timedelta(days=5),
                ends_at=now + timedelta(days=1),
                actor=self.reviewer,
            )

    def test_leave_requires_reviewer_qualification(self):
        now = timezone.now()

        with self.assertRaises(ReviewError):
            set_reviewer_leave(
                reviewer=self.member,
                starts_at=now,
                ends_at=now + timedelta(days=1),
                actor=self.member,
            )

    def test_a_preliminary_reviewer_may_register_leave_too(self):
        """初审人也要能请假：窗口说的是这个人现在不在，与任务种类无关。"""
        now = timezone.now()

        leave = set_reviewer_leave(
            reviewer=self.preliminary,
            starts_at=now,
            ends_at=now + timedelta(days=2),
            reason="出差",
            actor=self.preliminary,
        )

        self.assertEqual(leave.reviewer, self.preliminary)
        self.assertEqual(leave.state, ReviewerLeave.LEAVE_ACTIVE)

    def test_clearing_without_an_open_leave_is_an_error(self):
        with self.assertRaises(ReviewError):
            clear_reviewer_leave(reviewer=self.reviewer, actor=self.reviewer)

    # --- the member-centre form and views -----------------------------------

    def test_leave_form_parses_datetime_local_values(self):
        starts = timezone.localtime(timezone.now() + timedelta(days=1))
        ends = starts + timedelta(days=3)
        form = ReviewerLeaveForm(
            data={
                "starts_at": starts.strftime("%Y-%m-%dT%H:%M"),
                "ends_at": ends.strftime("%Y-%m-%dT%H:%M"),
                "reason": "考试周",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertTrue(timezone.is_aware(form.cleaned_data["starts_at"]))

    def test_leave_form_rejects_an_end_before_the_start(self):
        starts = timezone.localtime(timezone.now() + timedelta(days=5))
        form = ReviewerLeaveForm(
            data={
                "starts_at": starts.strftime("%Y-%m-%dT%H:%M"),
                "ends_at": (starts - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M"),
                "reason": "",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("ends_at", form.errors)

    def test_leave_views_require_reviewer_qualification(self):
        self.client.force_login(self.member)

        self.assertEqual(
            self.client.post(reverse("reviews:set_leave"), {}).status_code, 403
        )
        self.assertEqual(
            self.client.post(reverse("reviews:cancel_leave")).status_code, 403
        )

    def test_leave_views_reject_get(self):
        self.client.force_login(self.reviewer)

        self.assertEqual(self.client.get(reverse("reviews:set_leave")).status_code, 405)
        self.assertEqual(self.client.get(reverse("reviews:cancel_leave")).status_code, 405)

    def test_reviewer_registers_and_cancels_leave_via_view(self):
        starts = timezone.localtime(timezone.now())
        ends = starts + timedelta(days=4)
        self.client.force_login(self.reviewer)

        response = self.client.post(
            reverse("reviews:set_leave"),
            {
                "starts_at": starts.strftime("%Y-%m-%dT%H:%M"),
                "ends_at": ends.strftime("%Y-%m-%dT%H:%M"),
                "reason": "考试周",
            },
        )
        self.assertEqual(response.status_code, 302)
        leave = ReviewerLeave.objects.get(reviewer=self.reviewer)
        self.assertEqual(leave.reason, "考试周")
        self.assertEqual(leave.created_by, self.reviewer)
        home = self.client.get(reverse("accounts:member_home"))
        self.assertContains(home, "请假中")

        cancel = self.client.post(reverse("reviews:cancel_leave"))

        self.assertEqual(cancel.status_code, 302)
        self.assertFalse(ReviewerLeave.objects.filter(reviewer=self.reviewer).exists())

    def test_member_home_hides_the_leave_panel_from_non_reviewers(self):
        self.client.force_login(self.member)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "评审请假")

    def test_member_home_offers_the_leave_panel_to_a_preliminary_reviewer(self):
        self.client.force_login(self.preliminary)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertContains(response, "评审请假")

    def test_member_home_shows_when_recovery_happens(self):
        leave = self._leave(starts_in=-1, ends_in=2)
        self.client.force_login(self.reviewer)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertContains(response, "请假中")
        self.assertContains(response, timezone.localtime(leave.ends_at).strftime("%m-%d %H:%M"))

    def test_member_home_shows_recovery_to_a_preliminary_reviewer_too(self):
        """请假窗口对初审人同样生效，恢复时间也要在成员中心看得到。"""
        leave = self._leave(reviewer=self.preliminary, starts_in=-1, ends_in=2)
        self.client.force_login(self.preliminary)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertContains(response, "请假中")
        self.assertContains(response, timezone.localtime(leave.ends_at).strftime("%m-%d %H:%M"))

    def test_leave_panel_sits_below_the_operation_entries(self):
        self.client.force_login(self.reviewer)

        response = self.client.get(reverse("accounts:member_home"))
        html = response.content.decode()

        self.assertLess(html.index("可用入口"), html.index("评审请假"))
        # Django 模板不校验 HTML 嵌套：区块顺序对了但标签没配平，页面照样渲染 200，
        # 所以这里顺带盯住 div 配平。
        self.assertEqual(html.count("<div"), html.count("</div>"))

    # --- administrator side --------------------------------------------------

    def test_admin_lists_every_leave_with_editable_times(self):
        self._leave(starts_in=-1, ends_in=2, reason="考试周")
        self.client.force_login(self.admin)

        response = self.client.get(reverse("admin:reviews_reviewerleave_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "leave-reviewer")
        self.assertContains(response, "考试周")
        self.assertContains(response, "请假中")
        # list_editable renders the two timestamps as inputs on the changelist.
        self.assertContains(response, "form-0-starts_at_0")
        self.assertContains(response, "form-0-ends_at_1")

    def test_admin_can_move_the_recovery_time(self):
        leave = self._leave(starts_in=-1, ends_in=2)
        new_end = timezone.localtime(leave.ends_at + timedelta(days=3))
        start = timezone.localtime(leave.starts_at)
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("admin:reviews_reviewerleave_changelist"),
            {
                "form-TOTAL_FORMS": "1",
                "form-INITIAL_FORMS": "1",
                "form-MIN_NUM_FORMS": "0",
                "form-MAX_NUM_FORMS": "1000",
                "form-0-id": str(leave.pk),
                "form-0-starts_at_0": start.strftime("%Y-%m-%d"),
                "form-0-starts_at_1": start.strftime("%H:%M:%S"),
                "form-0-ends_at_0": new_end.strftime("%Y-%m-%d"),
                "form-0-ends_at_1": new_end.strftime("%H:%M:%S"),
                "_save": "保存",
            },
        )

        self.assertEqual(response.status_code, 302)
        leave.refresh_from_db()
        self.assertEqual(leave.ends_at, new_end.replace(microsecond=0))
        self.assertTrue(
            AuditLog.objects.filter(action="reviews.leave.admin_save").exists()
        )


