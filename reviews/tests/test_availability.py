"""接单开关：关掉就不再被抽中、不进改派候选，手上还有任务时关不掉。

它替换掉的是一套「请假窗口」（起止两个时间点 + 事由 + 到点自动恢复）。最大的
差别是**没有时间**：开关是本人此刻的状态，打开就恢复，所以这里没有一条围着时间
转的断言，也不需要任何定时任务。另一处容易记混的是**两道关各管各的**——窗口
那套是共用的（请假就两道都不接），现在关掉评审不影响被抽为初审人。

开关与资格是两件事：本文件里凡是「关掉」的断言，都不该出现 ``is_reviewer`` /
``is_preliminary_reviewer`` 被改动。
"""

from django.contrib.auth import get_user_model
from django.urls import reverse

from core.models import AuditLog

from .. import lifecycle
from ..models import ProjectSubmission, REVIEW_TYPE_INNOVATION_MIDTERM, ReviewTask
from ..services import (
    ReviewError,
    reassign_task,
    set_reviewer_availability,
    submit_verdict,
)
from .base import ONE_REVIEWER_TYPE, ReviewTestCase
from .factories import (
    make_admin,
    make_group,
    make_preliminary_reviewer,
    make_reviewer,
    make_user,
)


User = get_user_model()

#: 送审类型 → 两个阶段名，写断言时少打几个字。
PRELIMINARY = lifecycle.STAGE_PRELIMINARY
REVIEW = lifecycle.STAGE_REVIEW


class ReviewerAvailabilityTests(ReviewTestCase):
    #: 只开一人的轮次：候选人数少，抽签结果才写得死。
    round_type = ONE_REVIEWER_TYPE

    def setUp(self):
        self.admin = make_admin("availability-admin")
        self.contact = make_user("availability-contact")
        self.reviewer = make_reviewer("availability-reviewer")
        self.preliminary = make_preliminary_reviewer("availability-preliminary")
        self.member = make_user("availability-member")
        self.group = make_group("接单开关项目组", leader=self.contact)

    def _close(self, reviewer, stage):
        return set_reviewer_availability(
            reviewer=reviewer, stage=stage, receives=False, actor=reviewer
        )

    def _open(self, reviewer, stage):
        return set_reviewer_availability(
            reviewer=reviewer, stage=stage, receives=True, actor=reviewer
        )

    def _draw_one(self):
        """送审一轮并过初审，返回抽到的评审人。"""
        submission = self._open_round()
        self._pass_preliminary(submission)
        return self.review_tasks(submission).get().reviewer

    # --- 对抽签的影响 -------------------------------------------------------

    def test_a_closed_reviewer_is_not_drawn(self):
        other = make_reviewer("availability-reviewer-two")
        self._close(self.reviewer, REVIEW)

        self.assertEqual(self._draw_one(), other)

    def test_reopening_restores_immediately(self):
        """开关一变，下一次抽签立刻按新状态走——没有「窗口到点」这回事。"""
        other = make_reviewer("availability-reviewer-two")
        self._close(self.reviewer, REVIEW)
        self._close(other, REVIEW)

        self._open(self.reviewer, REVIEW)

        self.assertEqual(self._draw_one(), self.reviewer)

    def test_a_closed_preliminary_reviewer_is_not_drawn_for_preliminary(self):
        other = make_preliminary_reviewer("availability-preliminary-two")
        self._close(self.preliminary, PRELIMINARY)

        drawn = self._open_round().preliminary_task.reviewer

        self.assertEqual(drawn, other)

    def test_the_two_stages_have_separate_switches(self):
        """关掉初审不等于关掉评审：窗口那套是共用的，开关不是。

        同一份名单决定「谁会出现在哪一道关」——把初审人同时给评审资格，关掉他的
        初审开关之后他照旧能被抽为评审人。
        """
        self.preliminary.is_reviewer = True
        self.preliminary.save(update_fields=["is_reviewer"])
        # 初审那一道关得另有其人，这一轮才开得出来。
        make_preliminary_reviewer("availability-preliminary-two")
        self._close(self.preliminary, PRELIMINARY)
        # 评审池里只留他一个：抽签结果才不是运气（池里有两个人时断言会时灵时不灵）。
        self._close(self.reviewer, REVIEW)

        submission = self._open_round()
        self._pass_preliminary(submission)

        self.assertEqual(self.review_tasks(submission).get().reviewer, self.preliminary)
        # 而初审那一关确实换人了——同一份数据，两道开关各管各的。
        self.assertNotEqual(submission.preliminary_task.reviewer, self.preliminary)

    def test_closed_reviewers_are_named_in_the_shortage_message(self):
        self._close(self.reviewer, REVIEW)

        with self.assertRaises(ReviewError) as caught:
            self._open_round(review_type=REVIEW_TYPE_INNOVATION_MIDTERM)

        self.assertIn("另有 1 人已关闭接收新任务", str(caught.exception))

    def test_the_note_counts_only_accounts_holding_this_stages_qualification(self):
        """「另有 N 人已关闭」只算这一道关的人：初审关掉与评审人缺口无关。"""
        make_preliminary_reviewer("availability-preliminary-two")
        self._close(self.preliminary, PRELIMINARY)

        with self.assertRaises(ReviewError) as caught:
            self._open_round(review_type=REVIEW_TYPE_INNOVATION_MIDTERM)

        self.assertIn("评审人不足", str(caught.exception))
        self.assertNotIn("已关闭", str(caught.exception))

    # --- 改派候选 -----------------------------------------------------------

    def test_a_closed_reviewer_is_not_offered_for_reassignment(self):
        submission = self._submit()
        assignment = self.review_tasks(submission).first()
        spare = make_reviewer("availability-spare")
        self._close(spare, REVIEW)

        with self.assertRaises(ReviewError):
            reassign_task(task=assignment, new_reviewer=spare, actor=self.admin)

    # --- 关闭的门槛：手上还有未完成的任务 -----------------------------------

    def test_cannot_close_while_holding_a_pending_task(self):
        submission = self._submit()
        # 单评审人轮次、候选只有他，所以任务一定在 self.reviewer 手上、且还没交。
        self.assertIn(
            self.reviewer.pk,
            self.review_tasks(submission).values_list("reviewer_id", flat=True),
        )

        with self.assertRaises(ReviewError) as caught:
            self._close(self.reviewer, REVIEW)

        self.assertIn("手上还有 1 件未完成的评审任务", str(caught.exception))
        self.reviewer.refresh_from_db()
        self.assertTrue(self.reviewer.receives_review_tasks)

    def test_cannot_close_while_holding_a_pending_preliminary_task(self):
        submission = self._open_round()

        with self.assertRaises(ReviewError) as caught:
            self._close(self.preliminary, PRELIMINARY)

        self.assertIn("手上还有 1 件未完成的初审任务", str(caught.exception))
        self.assertEqual(
            submission.preliminary_task.status, ReviewTask.PENDING
        )

    def test_can_close_once_the_task_is_answered(self):
        submission = self._submit()
        assignment = self.review_tasks(submission).get()
        submit_verdict(
            task=assignment,
            reviewer=assignment.reviewer,
            decision=ReviewTask.APPROVE,
            comment="同意。",
        )

        self.assertTrue(self._close(self.reviewer, REVIEW))

        self.reviewer.refresh_from_db()
        self.assertFalse(self.reviewer.receives_review_tasks)

    def test_a_released_task_also_frees_the_switch(self):
        """任务被释放（比如超级评审一票敲定）之后同样关得掉。"""
        submission = self._submit()
        assignment = self.review_tasks(submission).get()
        assignment.status = ReviewTask.RELEASED
        assignment.save(update_fields=["status"])

        self.assertTrue(self._close(self.reviewer, REVIEW))

    # --- 服务层的其余规则 ---------------------------------------------------

    def test_setting_the_same_value_is_a_noop_and_leaves_no_audit(self):
        before = AuditLog.objects.count()

        self.assertFalse(self._open(self.reviewer, REVIEW))

        self.assertEqual(AuditLog.objects.count(), before)

    def test_the_switch_requires_the_stage_qualification(self):
        with self.assertRaises(ReviewError):
            self._close(self.member, REVIEW)
        with self.assertRaises(ReviewError):
            self._close(self.reviewer, PRELIMINARY)

    def test_an_unknown_stage_is_refused(self):
        with self.assertRaises(ReviewError):
            self._close(self.reviewer, "nonsense")

    def test_closing_never_touches_the_qualification(self):
        self._close(self.reviewer, REVIEW)

        self.reviewer.refresh_from_db()
        self.assertTrue(self.reviewer.is_reviewer)
        self.assertFalse(self.reviewer.receives_review_tasks)

    def test_opening_and_closing_are_audited_with_the_stage(self):
        self._close(self.reviewer, REVIEW)

        closed = AuditLog.objects.get(action="reviews.availability.close")
        self.assertEqual(closed.user, self.reviewer)
        self.assertEqual(closed.target_id, str(self.reviewer.pk))
        self.assertEqual(closed.detail["stage"], REVIEW)
        self.assertEqual(closed.detail["pending_tasks"], 0)

        self._open(self.reviewer, REVIEW)

        self.assertTrue(
            AuditLog.objects.filter(action="reviews.availability.open").exists()
        )

    def test_an_administrator_may_flip_someone_elses_switch(self):
        """代做：后台动作就是这么调的（谁能替谁做由调用方把关）。"""
        set_reviewer_availability(
            reviewer=self.reviewer,
            stage=REVIEW,
            receives=False,
            actor=self.admin,
        )

        self.reviewer.refresh_from_db()
        self.assertFalse(self.reviewer.receives_review_tasks)
        entry = AuditLog.objects.get(action="reviews.availability.close")
        self.assertEqual(entry.user, self.admin)
        self.assertEqual(entry.target_id, str(self.reviewer.pk))

    # --- 成员中心的开关与视图 -----------------------------------------------

    def test_the_view_requires_a_review_qualification(self):
        self.client.force_login(self.member)

        response = self.client.post(
            reverse("reviews:set_availability"),
            {"stage": REVIEW, "receives": "0"},
        )

        self.assertEqual(response.status_code, 403)

    def test_the_view_rejects_get(self):
        self.client.force_login(self.reviewer)

        response = self.client.get(reverse("reviews:set_availability"))

        self.assertEqual(response.status_code, 405)

    def test_an_unknown_stage_is_a_404(self):
        self.client.force_login(self.reviewer)

        response = self.client.post(
            reverse("reviews:set_availability"),
            {"stage": "nonsense", "receives": "0"},
        )

        self.assertEqual(response.status_code, 404)

    def test_a_reviewer_closes_and_reopens_their_own_switch(self):
        self.client.force_login(self.reviewer)

        closed = self.client.post(
            reverse("reviews:set_availability"),
            {"stage": REVIEW, "receives": "0"},
        )
        self.assertEqual(closed.status_code, 302)
        self.reviewer.refresh_from_db()
        self.assertFalse(self.reviewer.receives_review_tasks)

        reopened = self.client.post(
            reverse("reviews:set_availability"),
            {"stage": REVIEW, "receives": "1"},
        )
        self.assertEqual(reopened.status_code, 302)
        self.reviewer.refresh_from_db()
        self.assertTrue(self.reviewer.receives_review_tasks)

    def test_the_view_explains_why_a_close_was_refused(self):
        self._submit()
        self.client.force_login(self.reviewer)

        response = self.client.post(
            reverse("reviews:set_availability"),
            {"stage": REVIEW, "receives": "0"},
            follow=True,
        )

        self.assertContains(response, "手上还有 1 件未完成的评审任务")
        self.reviewer.refresh_from_db()
        self.assertTrue(self.reviewer.receives_review_tasks)

    def test_member_home_shows_the_switch_and_the_pending_count(self):
        self._submit()
        self.client.force_login(self.reviewer)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertContains(response, "接单状态")
        self.assertContains(response, "接收中")
        self.assertContains(response, "手上还有 1 件未完成的任务")

    def test_member_home_shows_a_closed_switch(self):
        self._close(self.reviewer, REVIEW)
        self.client.force_login(self.reviewer)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertContains(response, "已关闭")
        self.assertContains(response, "恢复接收评审任务")

    def test_member_home_offers_the_switch_to_a_preliminary_reviewer_too(self):
        self.client.force_login(self.preliminary)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertContains(response, "接单状态")
        self.assertContains(response, "暂停接收初审任务")

    def test_member_home_hides_the_panel_from_non_reviewers(self):
        self.client.force_login(self.member)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "接单状态")

    def test_the_switch_panel_sits_below_the_operation_entries(self):
        self.client.force_login(self.reviewer)

        response = self.client.get(reverse("accounts:member_home"))
        html = response.content.decode()

        self.assertLess(html.index("可用入口"), html.index("接单状态"))
        # Django 模板不校验 HTML 嵌套：区块顺序对了但标签没配平，页面照样渲染 200，
        # 所以这里顺带盯住 div 配平。
        self.assertEqual(html.count("<div"), html.count("</div>"))

    # --- 后台：一列状态 + 两个可代做的动作 ----------------------------------

    def test_the_user_list_shows_who_closed_their_switch(self):
        self._close(self.reviewer, REVIEW)
        self.client.force_login(self.admin)

        response = self.client.get(reverse("admin:accounts_user_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "已关闭评审")
        self.assertContains(response, "availability-reviewer")

    def test_the_admin_action_closes_and_reopens_both_stages(self):
        self.client.force_login(self.admin)
        url = reverse("admin:accounts_user_changelist")

        closed = self.client.post(
            url,
            {
                "action": "close_availability",
                "_selected_action": [str(self.reviewer.pk)],
            },
            follow=True,
        )
        self.assertContains(closed, "已暂停接收新任务：1 人。")
        self.reviewer.refresh_from_db()
        self.assertFalse(self.reviewer.receives_review_tasks)

        reopened = self.client.post(
            url,
            {
                "action": "open_availability",
                "_selected_action": [str(self.reviewer.pk)],
            },
            follow=True,
        )
        self.assertContains(reopened, "已恢复接收新任务：1 人。")
        self.reviewer.refresh_from_db()
        self.assertTrue(self.reviewer.receives_review_tasks)

    def test_the_admin_action_reports_who_could_not_be_closed(self):
        """管理员也受同一条规则约束：手上有未完成任务的人关不掉，且单独报出来。"""
        self._submit()
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("admin:accounts_user_changelist"),
            {
                "action": "close_availability",
                "_selected_action": [str(self.reviewer.pk)],
            },
            follow=True,
        )

        self.assertContains(response, "1 人手上还有未完成的任务，未暂停")
        self.reviewer.refresh_from_db()
        self.assertTrue(self.reviewer.receives_review_tasks)

    def test_the_admin_action_skips_accounts_without_any_qualification(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("admin:accounts_user_changelist"),
            {
                "action": "close_availability",
                "_selected_action": [str(self.member.pk)],
            },
            follow=True,
        )

        self.assertContains(response, "接单状态没有变化")
        self.assertFalse(
            AuditLog.objects.filter(action="reviews.availability.close").exists()
        )


class AvailabilityPoolTests(ReviewTestCase):
    """候选名单本身：开关只影响一道关，且资格一个都没变。"""

    def setUp(self):
        self.admin = make_admin("pool-admin")
        self.contact = make_user("pool-contact")
        self.reviewer = make_reviewer("pool-reviewer")
        self.preliminary = make_preliminary_reviewer("pool-preliminary")
        self.group = make_group("候选名单项目组", leader=self.contact)

    def test_the_pool_excludes_only_the_stage_whose_switch_is_off(self):
        from ..draw import eligible_holders

        self.reviewer.receives_review_tasks = False
        self.reviewer.is_preliminary_reviewer = True
        self.reviewer.save(
            update_fields=["receives_review_tasks", "is_preliminary_reviewer"]
        )

        submission = ProjectSubmission.objects.create(
            group=self.group,
            round=1,
            review_type=REVIEW_TYPE_INNOVATION_MIDTERM,
            submitted_by=self.contact,
        )

        review_pool = eligible_holders(
            stage=REVIEW, group=self.group, submitter=self.contact, submission=submission
        )
        preliminary_pool = eligible_holders(
            stage=PRELIMINARY,
            group=self.group,
            submitter=self.contact,
            submission=submission,
        )

        self.assertNotIn(self.reviewer, review_pool)
        self.assertIn(self.reviewer, preliminary_pool)
