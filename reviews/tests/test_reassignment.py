"""管理员改派评审人：评审人失联或事后发现利益冲突时的唯一补救路径。

只有「待处理且该轮未判结论」的任务能换人，且改派者必须真的持有该模型的修改
权限——只读账号不行。换了人不需要重新判结论，也完全不触碰归档。
"""

from datetime import timedelta

from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog

from .. import lifecycle
from ..models import (
    ProjectSubmission,
    ReviewTask,
    ReviewerLeave,
)
from ..services import (
    ReviewError,
    submit_verdict,
    eligible_holders,
    reassign_task,
)
from .base import ReviewTestCase
from .factories import (
    make_admin,
    make_group,
    make_preliminary_reviewer,
    make_reviewer,
    make_user,
)


class ReviewTaskReassignmentTests(ReviewTestCase):
    """An administrator can hand a still-pending task to a different reviewer.

    Either the reviewer went quiet or turns out to have a conflict of interest;
    without this the round sits at 评审中 forever. Verdicts are never rewritten,
    so the permission stops at tasks pending on a round that has not been decided.
    """

    def setUp(self):
        self.admin = make_admin("swap-admin")
        self.contact = make_user("swap-contact")
        self.member = make_user("swap-member")
        self.outsider = make_user("swap-outsider")
        self.reviewers = [
            make_reviewer(name)
            for name in ("swap-reviewer-one", "swap-reviewer-two", "swap-reviewer-three")
        ]
        self.preliminary = make_preliminary_reviewer("swap-preliminary")
        # 本类只关心「有一份项目书」这个事实，不读文件内容，所以不落盘。
        self.group = make_group(
            "换人项目组", leader=self.contact, members=[self.member], write_proposal=False
        )
    """An administrator can hand a still-pending task to a different reviewer.

    This is the only recovery path for a round whose reviewer went quiet or
    turned out to have a conflict of interest — without it such a round sits at
    评审中 forever. Verdicts are never rewritten, so the permission is limited to
    tasks that are pending on a round that has not been decided.
    """

    def _spare_reviewer(self, submission):
        assigned = set(self.review_tasks(submission).values_list("reviewer_id", flat=True))
        return next(user for user in self.reviewers if user.pk not in assigned)

    def _change_url(self, assignment):
        return reverse(
            "admin:reviews_reviewtask_change", args=(assignment.pk,)
        )

    # --- the service ---------------------------------------------------------

    def test_swapping_moves_the_task_to_the_new_reviewer(self):
        submission = self._submit()
        assignment = self.review_tasks(submission).first()
        spare = self._spare_reviewer(submission)

        reassign_task(task=assignment, new_reviewer=spare, actor=self.admin)

        assignment.refresh_from_db()
        self.assertEqual(assignment.reviewer, spare)
        # 换人不改变任务数与状态，因此无需重新判结论。
        self.assertEqual(assignment.status, ReviewTask.PENDING)
        self.assertEqual(self.review_tasks(submission).count(), 2)
        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.PENDING)
        audit = AuditLog.objects.get(action="reviews.assignment.reassign")
        self.assertEqual(audit.detail["to_reviewer_id"], spare.pk)

    def test_a_completed_task_cannot_be_swapped(self):
        submission = self._submit()
        assignment = self.review_tasks(submission).first()
        submit_verdict(
            task=assignment,
            reviewer=assignment.reviewer,
            decision=ReviewTask.APPROVE,
            comment="同意。",
        )
        assignment.refresh_from_db()
        spare = self._spare_reviewer(submission)

        with self.assertRaises(ReviewError):
            reassign_task(task=assignment, new_reviewer=spare, actor=self.admin)

        assignment.refresh_from_db()
        self.assertNotEqual(assignment.reviewer, spare)
        # 已经落下的结论、意见不能被换人改写。
        self.assertEqual(assignment.comment, "同意。")

    def test_a_round_that_already_has_a_verdict_cannot_be_swapped(self):
        """Guards an abnormal state:正常流程下判结论的前提就是没有待评审任务。"""
        submission = self._submit()
        assignment = self.review_tasks(submission).first()
        spare = self._spare_reviewer(submission)
        ProjectSubmission.objects.filter(pk=submission.pk).update(
            status=ProjectSubmission.APPROVED
        )

        with self.assertRaises(ReviewError):
            reassign_task(task=assignment, new_reviewer=spare, actor=self.admin)

    def test_the_current_reviewer_is_not_a_change(self):
        submission = self._submit()
        assignment = self.review_tasks(submission).first()

        with self.assertRaises(ReviewError):
            reassign_task(
                task=assignment,
                new_reviewer=assignment.reviewer,
                actor=self.admin,
            )

    def test_the_submitter_cannot_be_swapped_in(self):
        submission = self._submit()
        assignment = self.review_tasks(submission).first()

        with self.assertRaises(ReviewError):
            reassign_task(
                task=assignment, new_reviewer=self.contact, actor=self.admin
            )

    def test_a_group_member_cannot_be_swapped_in(self):
        submission = self._submit()
        assignment = self.review_tasks(submission).first()
        self.member.is_reviewer = True
        self.member.save(update_fields=["is_reviewer"])

        with self.assertRaises(ReviewError):
            reassign_task(
                task=assignment, new_reviewer=self.member, actor=self.admin
            )

    def test_someone_already_on_the_round_cannot_be_swapped_in(self):
        submission = self._submit()
        assignment = self.review_tasks(submission).first()
        other = self.review_tasks(submission).exclude(pk=assignment.pk).get().reviewer

        with self.assertRaises(ReviewError) as caught:
            reassign_task(
                task=assignment, new_reviewer=other, actor=self.admin
            )

        # 拒绝文案与初审侧同源（StageRules），不再各写一句。
        self.assertEqual(
            str(caught.exception),
            lifecycle.STAGES[lifecycle.STAGE_REVIEW].swap_holds,
        )

    def test_a_non_reviewer_cannot_be_swapped_in(self):
        submission = self._submit()
        assignment = self.review_tasks(submission).first()

        with self.assertRaises(ReviewError):
            reassign_task(
                task=assignment, new_reviewer=self.outsider, actor=self.admin
            )

    def test_an_inactive_reviewer_cannot_be_swapped_in(self):
        submission = self._submit()
        assignment = self.review_tasks(submission).first()
        spare = self._spare_reviewer(submission)
        spare.is_active = False
        spare.save(update_fields=["is_active"])

        with self.assertRaises(ReviewError):
            reassign_task(task=assignment, new_reviewer=spare, actor=self.admin)

    def test_a_reviewer_on_leave_cannot_be_swapped_in(self):
        submission = self._submit()
        assignment = self.review_tasks(submission).first()
        spare = self._spare_reviewer(submission)
        now = timezone.now()
        ReviewerLeave.objects.create(
            reviewer=spare,
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=7),
        )

        with self.assertRaises(ReviewError):
            reassign_task(task=assignment, new_reviewer=spare, actor=self.admin)

    def test_the_rounds_preliminary_reviewer_cannot_be_swapped_in(self):
        """一个人既初审又评审时，也不接自己初审通过的那一轮。"""
        submission = self._submit()
        assignment = self.review_tasks(submission).first()
        self.preliminary.is_reviewer = True
        self.preliminary.save(update_fields=["is_reviewer"])

        with self.assertRaises(ReviewError):
            reassign_task(
                task=assignment,
                new_reviewer=self.preliminary,
                actor=self.admin,
            )

        # 候选名单同样不包含他。
        candidates = eligible_holders(stage=ReviewTask.REVIEW, 
            group=self.group, submitter=self.contact, submission=submission
        )
        self.assertNotIn(self.preliminary, candidates)

    # --- the admin change page ----------------------------------------------

    def test_admin_offers_the_reviewer_dropdown_for_a_pending_task(self):
        submission = self._submit()
        assignment = self.review_tasks(submission).first()
        spare = self._spare_reviewer(submission)
        self.client.force_login(self.admin)

        response = self.client.get(self._change_url(assignment))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="reviewer"')
        candidates = set(
            response.context["adminform"]
            .form.fields["reviewer"]
            .queryset.values_list("pk", flat=True)
        )
        # 当前评审人留着（否则下拉看不出现在是谁），空余的那位可选；
        # 提交人、组员、本轮另一条任务的评审人都不在候选里。
        self.assertEqual(candidates, {assignment.reviewer_id, spare.pk})

    def test_admin_change_page_is_read_only_for_a_completed_task(self):
        submission = self._submit()
        assignment = self.review_tasks(submission).first()
        submit_verdict(
            task=assignment,
            reviewer=assignment.reviewer,
            decision=ReviewTask.APPROVE,
            comment="同意。",
        )
        self.client.force_login(self.admin)

        response = self.client.get(self._change_url(assignment))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="reviewer"')

    def test_admin_swaps_the_reviewer(self):
        submission = self._submit()
        assignment = self.review_tasks(submission).first()
        spare = self._spare_reviewer(submission)
        self.client.force_login(self.admin)

        response = self.client.post(
            self._change_url(assignment),
            {"reviewer": spare.pk, "_save": "保存"},
        )

        self.assertEqual(response.status_code, 302)
        assignment.refresh_from_db()
        self.assertEqual(assignment.reviewer, spare)
        self.assertTrue(
            AuditLog.objects.filter(action="reviews.assignment.reassign").exists()
        )

    def test_admin_cannot_post_a_swap_for_a_completed_task(self):
        submission = self._submit()
        assignment = self.review_tasks(submission).first()
        submit_verdict(
            task=assignment,
            reviewer=assignment.reviewer,
            decision=ReviewTask.APPROVE,
            comment="同意。",
        )
        assignment.refresh_from_db()
        original_reviewer_id = assignment.reviewer_id
        spare = self._spare_reviewer(submission)
        self.client.force_login(self.admin)

        response = self.client.post(
            self._change_url(assignment),
            {"reviewer": spare.pk, "_save": "保存"},
        )

        self.assertEqual(response.status_code, 403)
        assignment.refresh_from_db()
        self.assertEqual(assignment.reviewer_id, original_reviewer_id)

    def test_a_view_only_staff_account_cannot_swap_the_reviewer(self):
        """状态允许不等于有权改：只有查看权限的后台账号不能改派。"""
        submission = self._submit()
        assignment = self.review_tasks(submission).first()
        original_reviewer_id = assignment.reviewer_id
        spare = self._spare_reviewer(submission)
        viewer = make_user("swap-viewer", is_staff=True)
        viewer.user_permissions.add(
            Permission.objects.get(codename="view_reviewtask")
        )
        url = self._change_url(assignment)
        self.client.force_login(viewer)

        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'name="reviewer"')

        response = self.client.post(url, {"reviewer": spare.pk, "_save": "保存"})

        self.assertEqual(response.status_code, 403)
        assignment.refresh_from_db()
        self.assertEqual(assignment.reviewer_id, original_reviewer_id)

    def test_admin_cannot_delete_a_task(self):
        submission = self._submit()
        assignment = self.review_tasks(submission).first()
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("admin:reviews_reviewtask_delete", args=(assignment.pk,))
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(ReviewTask.objects.filter(pk=assignment.pk).exists())


