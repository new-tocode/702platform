"""初审关卡：通过才进评审，打回则本轮直接结束。

初审只有一个位置、一对与评审共用的结论取值，而且通过它的那个人不会再被抽进
这一轮的评审人里——一个人既放行又评审，等于让同一份意见在一轮里占两个位置。
"""

from datetime import timedelta

from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog
from core.registry import get_entries_for_user

from ..forms import PreliminaryReviewForm
from .. import lifecycle
from ..models import (
    REVIEW_TYPE_COMPETITION_PROJECT,
    ArchivedProposal,
    PreliminaryReview,
    ProjectSubmission,
    ReviewAssignment,
    ReviewerLeave,
    preliminary_review_of,
)
from ..services import (
    ReviewError,
    complete_preliminary_review,
    count_pending_preliminary_reviews,
    eligible_preliminary_reviewers,
    eligible_reviewers,
    reassign_preliminary_reviewer,
)
from .base import (
    TWO_REVIEWER_TYPE,
    ReviewTestCase,
)
from .factories import (
    make_admin,
    make_group,
    make_preliminary_reviewer,
    make_reviewer,
    make_user,
    qualify,
)


class PreliminaryReviewTests(ReviewTestCase):
    """送审先过初审人这一关，通过后才抽评审人。

    初审是「关卡」而不是评审团：只有一个位置（一对一）、只有与评审同一对结论
    （通过 / 需修改），而且通过它的那个人不会再被抽进这一轮的评审人里。
    """

    def setUp(self):
        self.admin = make_admin("preliminary-admin")
        self.contact = make_user("preliminary-contact")
        self.member = make_user("preliminary-member")
        # 只放一位初审人在岗：抽签结果确定，断言才写得住。
        self.preliminary = make_preliminary_reviewer("preliminary-one")
        self.reviewer_one = make_reviewer("preliminary-reviewer-one")
        self.reviewer_two = make_reviewer("preliminary-reviewer-two")
        self.outsider = make_user("preliminary-outsider")
        self.group = make_group("初审项目组", leader=self.contact, members=[self.member])
    """送审先过初审人这一关，通过后才抽评审人。

    初审是「关卡」而不是评审团：只有一个位置（一对一）、只有与评审同一对结论
    （通过 / 需修改），而且通过它的那个人不会再被抽进这一轮的评审人里——一个人
    既放行又评审，等于让同一份意见在一轮里占两个位置。
    """

    def _preliminary_url(self, preliminary):
        return reverse("reviews:preliminary_complete", args=(preliminary.pk,))

    # --- the gate ------------------------------------------------------------

    def test_the_round_holds_exactly_one_preliminary_task(self):
        submission = self._open_round()

        self.assertEqual(
            PreliminaryReview.objects.filter(submission=submission).count(), 1
        )
        preliminary = preliminary_review_of(submission)
        self.assertEqual(preliminary.reviewer, self.preliminary)
        self.assertEqual(preliminary.status, PreliminaryReview.PENDING)
        self.assertEqual(submission.status, ProjectSubmission.PRELIMINARY_PENDING)
        self.assertTrue(submission.is_open)
        # 任务数算上初审：超级评审要释放的正是这些还没交的东西。
        self.assertEqual(submission.open_task_count, 1)
        self.assertEqual(submission.assignments.count(), 0)

    def test_approval_draws_the_reviewers_its_type_calls_for(self):
        submission = self._open_round()

        self._pass_preliminary(submission)

        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.PENDING)
        self.assertIsNone(submission.decided_at)
        self.assertEqual(submission.open_task_count, submission.required_reviewers)
        self.assertEqual(
            set(submission.assignments.values_list("reviewer_id", flat=True)),
            {self.reviewer_one.pk, self.reviewer_two.pk},
        )
        self.assertEqual(count_pending_preliminary_reviews(self.preliminary), 0)

    def test_capacity_check_leaves_the_preliminary_reviewer_out(self):
        """初审人不能占评审名额：预检要比「名义上有几个评审人」少算他一个。"""
        self.preliminary.is_reviewer = True
        self.preliminary.save(update_fields=["is_reviewer"])

        # 名义上有 3 名评审人（初审人也在其中），但初审人不能占名额，剩 2 人不够 3 人。
        with self.assertRaises(ReviewError) as caught:
            self._open_round(review_type=REVIEW_TYPE_COMPETITION_PROJECT)

        self.assertIn("3 人", str(caught.exception))
        self.assertFalse(ProjectSubmission.objects.exists())

    def test_approval_is_refused_when_the_pool_shrank_since_submission(self):
        """提交时够用、初审通过时不够了：整次回滚，任务仍在初审人手上。"""
        submission = self._open_round()
        self.reviewer_two.is_reviewer = False
        self.reviewer_two.save(update_fields=["is_reviewer"])

        with self.assertRaises(ReviewError) as caught:
            self._pass_preliminary(submission)

        self.assertIn("评审人", str(caught.exception))
        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.PRELIMINARY_PENDING)
        self.assertEqual(submission.assignments.count(), 0)
        preliminary = preliminary_review_of(submission)
        self.assertEqual(preliminary.status, PreliminaryReview.PENDING)
        self.assertIsNone(preliminary.completed_at)

        # 有人可用之后原地重试即可，不必重新送审。
        self.reviewer_two.is_reviewer = True
        self.reviewer_two.save(update_fields=["is_reviewer"])
        self._pass_preliminary(submission)

        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.PENDING)
        self.assertEqual(submission.assignments.count(), 2)

    def test_a_revision_request_ends_the_round_without_reviewers(self):
        submission = self._open_round()

        self._pass_preliminary(
            submission,
            decision=PreliminaryReview.REVISE,
            comment="请先补齐预算。",
        )

        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.NEEDS_REVISION)
        self.assertIsNotNone(submission.decided_at)
        self.assertEqual(submission.assignments.count(), 0)
        self.assertFalse(ArchivedProposal.objects.filter(submission=submission).exists())
        # 打回不花评审人的时间：这一轮从头到尾没分配过评审任务。
        audit = AuditLog.objects.get(action="reviews.preliminary.complete")
        self.assertEqual(audit.detail["reviewer_ids"], [])
        self.assertEqual(
            audit.detail["submission_status"], ProjectSubmission.NEEDS_REVISION
        )

    def test_audit_log_records_who_passed_the_round(self):
        submission = self._open_round()

        self._pass_preliminary(submission)

        audit = AuditLog.objects.get(action="reviews.preliminary.complete")
        self.assertEqual(audit.user, self.preliminary)
        self.assertEqual(audit.detail["submission_id"], submission.pk)
        self.assertEqual(audit.detail["decision"], PreliminaryReview.APPROVE)
        self.assertEqual(audit.detail["submission_status"], ProjectSubmission.PENDING)
        self.assertEqual(
            set(audit.detail["reviewer_ids"]),
            {self.reviewer_one.pk, self.reviewer_two.pk},
        )

    def test_an_approving_preliminary_reviewer_is_not_drawn_as_a_reviewer(self):
        """同时具备两种资格的人，不接自己初审通过的那一轮。"""
        self.preliminary.is_reviewer = True
        self.preliminary.save(update_fields=["is_reviewer"])
        submission = self._open_round()
        self.assertEqual(preliminary_review_of(submission).reviewer, self.preliminary)

        self._pass_preliminary(submission)

        drawn = set(submission.assignments.values_list("reviewer_id", flat=True))
        self.assertEqual(drawn, {self.reviewer_one.pk, self.reviewer_two.pk})
        self.assertNotIn(self.preliminary.pk, drawn)
        # 候选池里也把他排除掉。
        self.assertNotIn(
            self.preliminary,
            eligible_reviewers(
                group=self.group, submitter=self.contact, submission=submission
            ),
        )
        # 排除只跟着「这一轮」走：不带 submission 的候选池里他仍在（资格未被改动）。
        self.assertIn(
            self.preliminary,
            eligible_reviewers(group=self.group, submitter=self.contact),
        )

    def test_a_completed_preliminary_cannot_be_answered_twice(self):
        submission = self._open_round()
        preliminary = preliminary_review_of(submission)
        self._pass_preliminary(submission)

        with self.assertRaises(ReviewError) as caught:
            complete_preliminary_review(
                preliminary=preliminary,
                reviewer=self.preliminary,
                decision=PreliminaryReview.APPROVE,
                comment="再判一次。",
            )

        self.assertIn("已经处理过", str(caught.exception))

    def test_someone_else_cannot_answer_my_preliminary(self):
        submission = self._open_round()
        other = make_preliminary_reviewer("preliminary-other")

        with self.assertRaises(ReviewError):
            complete_preliminary_review(
                preliminary=preliminary_review_of(submission),
                reviewer=other,
                decision=PreliminaryReview.APPROVE,
                comment="越权。",
            )

    def test_an_invalid_decision_is_refused(self):
        submission = self._open_round()
        preliminary = preliminary_review_of(submission)

        with self.assertRaises(ReviewError):
            complete_preliminary_review(
                preliminary=preliminary,
                reviewer=self.preliminary,
                decision="not-a-decision",
                comment="随便勾的。",
            )

        preliminary.refresh_from_db()
        self.assertEqual(preliminary.status, PreliminaryReview.PENDING)

    def test_the_gate_uses_the_same_verdicts_as_a_review(self):
        """同一对结论、同一套取值；初审只是没有批注版——它给的是理由，不是稿子。"""
        self.assertEqual(
            PreliminaryReview.DECISION_CHOICES, ReviewAssignment.DECISION_CHOICES
        )
        self.assertNotIn("annotated_file", PreliminaryReviewForm().fields)

    def test_the_group_is_pointed_at_the_preliminary_opinion_after_a_bounce(self):
        """初审打回时没有评审意见可看，页面不能让人去找不存在的东西。"""
        submission = self._open_round()
        self._pass_preliminary(
            submission, decision=PreliminaryReview.REVISE, comment="预算要重做。"
        )
        self.client.force_login(self.member)

        response = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )

        self.assertContains(response, "初审打回")
        self.assertContains(response, "预算要重做。")
        self.assertNotContains(response, "根据评审意见")

    # --- the 初审人's own pages ------------------------------------------------

    def test_queue_and_detail_serve_a_preliminary_only_account(self):
        submission = self._open_round()
        preliminary = preliminary_review_of(submission)
        self.client.force_login(self.preliminary)

        queue = self.client.get(reverse("reviews:queue"))
        detail = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )

        self.assertEqual(queue.status_code, 200)
        self.assertContains(queue, "待初审")
        self.assertContains(queue, self.group.name)
        self.assertEqual(len(queue.context["preliminary_pending"]), 1)
        # 没有评审资格，就不该看到评审那一侧的空面板。
        self.assertFalse(queue.context["show_review"])
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.context["my_preliminary"].pk, preliminary.pk)
        self.assertContains(detail, "我的初审")

    def test_the_review_entry_is_visible_to_a_preliminary_reviewer(self):
        keys = {entry.key for entry in get_entries_for_user(self.preliminary)}

        self.assertIn("reviews.queue", keys)

    def test_a_group_member_sees_the_preliminary_line_but_no_form(self):
        submission = self._open_round()
        self.client.force_login(self.member)

        response = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )

        self.assertContains(response, "待初审")
        self.assertNotContains(response, "我的初审")
        self.assertIsNone(response.context["my_preliminary"])
        # 初审人身份匿名：页面上不出现账号。
        self.assertNotContains(response, self.preliminary.username)
        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.PRELIMINARY_PENDING)

    def test_the_queue_hides_the_preliminary_side_from_a_plain_reviewer(self):
        self._open_round()
        self.client.force_login(self.reviewer_one)

        response = self.client.get(reverse("reviews:queue"))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["show_preliminary"])
        self.assertNotIn("preliminary_pending", response.context)
        self.assertNotContains(response, "待初审")

    def test_the_verdict_is_anonymous_on_the_group_detail(self):
        submission = self._open_round()
        self._pass_preliminary(submission)
        self.client.force_login(self.member)

        response = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )

        self.assertContains(response, "初审")
        self.assertContains(response, "同意送审。")
        self.assertNotContains(response, self.preliminary.username)

    def test_a_round_without_a_preliminary_task_still_renders(self):
        """升级前留下的轮次没有初审任务：页面照常渲染，也不凭空多出一行初审。"""
        legacy = ProjectSubmission.objects.create(
            group=self.group,
            round=1,
            review_type=TWO_REVIEWER_TYPE,
            status=ProjectSubmission.PENDING,
            submitted_by=self.contact,
        )
        ReviewAssignment.objects.create(submission=legacy, reviewer=self.reviewer_one)
        self.client.force_login(self.member)

        response = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["my_preliminary"])
        self.assertContains(response, "评审人 1")
        # 评审记录里不凭空多出一行初审（组名里带「初审」二字，所以只盯那一行）。
        self.assertNotContains(response, "<dt>初审</dt>")

    # --- the 初审 form post ---------------------------------------------------

    def test_the_view_requires_the_post_verb_and_the_holder(self):
        submission = self._open_round()
        url = self._preliminary_url(preliminary_review_of(submission))
        other = make_preliminary_reviewer("preliminary-other")
        payload = {"decision": PreliminaryReview.APPROVE, "comment": "同意。"}

        self.client.force_login(self.member)
        self.assertEqual(self.client.post(url, payload).status_code, 403)

        self.client.force_login(other)
        self.assertEqual(self.client.post(url, payload).status_code, 403)

        self.client.force_login(self.preliminary)
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_the_view_approves_and_says_what_it_assigned(self):
        submission = self._open_round()
        self.client.force_login(self.preliminary)

        response = self.client.post(
            self._preliminary_url(preliminary_review_of(submission)),
            {"decision": PreliminaryReview.APPROVE, "comment": "同意送审。"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "已随机分配 2 名评审人")
        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.PENDING)
        self.assertEqual(submission.assignments.count(), 2)

    def test_the_view_records_a_revision_request(self):
        submission = self._open_round()
        self.client.force_login(self.preliminary)

        response = self.client.post(
            self._preliminary_url(preliminary_review_of(submission)),
            {"decision": PreliminaryReview.REVISE, "comment": "预算要重做。"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "初审已打回")
        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.NEEDS_REVISION)
        self.assertEqual(submission.assignments.count(), 0)

    def test_the_view_refuses_an_empty_comment(self):
        submission = self._open_round()
        self.client.force_login(self.preliminary)

        response = self.client.post(
            self._preliminary_url(preliminary_review_of(submission)),
            {"decision": PreliminaryReview.APPROVE, "comment": ""},
        )

        self.assertEqual(response.status_code, 302)
        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.PRELIMINARY_PENDING)
        self.assertEqual(submission.assignments.count(), 0)

    # --- administrator side ---------------------------------------------------

    def test_reassigning_hands_the_gate_to_another_preliminary_reviewer(self):
        submission = self._open_round()
        preliminary = preliminary_review_of(submission)
        other = make_preliminary_reviewer("preliminary-spare")

        reassign_preliminary_reviewer(
            preliminary=preliminary, new_reviewer=other, actor=self.admin
        )

        preliminary.refresh_from_db()
        self.assertEqual(preliminary.reviewer, other)
        # 换人不改任务状态，也不动这一轮的轮次与结论。
        self.assertEqual(preliminary.status, PreliminaryReview.PENDING)
        self.assertEqual(count_pending_preliminary_reviews(other), 1)
        self.assertEqual(count_pending_preliminary_reviews(self.preliminary), 0)
        audit = AuditLog.objects.get(action="reviews.preliminary.reassign")
        self.assertEqual(audit.detail["to_reviewer_id"], other.pk)

    def test_swapping_in_someone_already_holding_a_task_is_refused(self):
        """一人一轮一席：初审侧与评审侧同一条检查。

        正常流程造不出这种数据（初审中还没有评审任务），所以直接落一条评审任务，
        测的正是该检查要拦的那种形态。
        """
        submission = self._open_round()
        preliminary = preliminary_review_of(submission)
        holder = make_user("preliminary-holder")
        ReviewAssignment.objects.create(submission=submission, reviewer=holder)

        with self.assertRaises(ReviewError) as caught:
            reassign_preliminary_reviewer(
                preliminary=preliminary, new_reviewer=holder, actor=self.admin
            )

        self.assertEqual(
            str(caught.exception),
            lifecycle.STAGES[lifecycle.STAGE_PRELIMINARY].swap_holds,
        )

    def test_a_completed_preliminary_cannot_be_swapped(self):
        submission = self._open_round()
        preliminary = preliminary_review_of(submission)
        self._pass_preliminary(submission)
        other = make_preliminary_reviewer("preliminary-spare")

        with self.assertRaises(ReviewError):
            reassign_preliminary_reviewer(
                preliminary=preliminary, new_reviewer=other, actor=self.admin
            )

        preliminary.refresh_from_db()
        self.assertEqual(preliminary.reviewer, self.preliminary)
        # 谁放行的这一轮不能被改写。
        self.assertEqual(preliminary.comment, "同意送审。")

    def test_the_submitter_and_group_members_cannot_be_swapped_in(self):
        submission = self._open_round()
        preliminary = preliminary_review_of(submission)
        qualify(self.contact, is_preliminary_reviewer=True)
        qualify(self.member, is_preliminary_reviewer=True)

        for candidate in (self.contact, self.member):
            with self.subTest(candidate=candidate.get_username()):
                with self.assertRaises(ReviewError):
                    reassign_preliminary_reviewer(
                        preliminary=preliminary,
                        new_reviewer=candidate,
                        actor=self.admin,
                    )

    def test_an_account_without_the_qualification_cannot_be_swapped_in(self):
        submission = self._open_round()
        preliminary = preliminary_review_of(submission)

        with self.assertRaises(ReviewError):
            reassign_preliminary_reviewer(
                preliminary=preliminary,
                new_reviewer=self.outsider,
                actor=self.admin,
            )

    def test_a_preliminary_reviewer_on_leave_cannot_be_swapped_in(self):
        submission = self._open_round()
        preliminary = preliminary_review_of(submission)
        other = make_preliminary_reviewer("preliminary-spare")
        now = timezone.now()
        ReviewerLeave.objects.create(
            reviewer=other,
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=7),
        )

        with self.assertRaises(ReviewError):
            reassign_preliminary_reviewer(
                preliminary=preliminary, new_reviewer=other, actor=self.admin
            )

    def test_the_candidate_pool_is_the_preliminary_one(self):
        submission = self._open_round()
        spare = make_preliminary_reviewer("preliminary-spare")

        candidates = eligible_preliminary_reviewers(
            group=self.group, submitter=self.contact, submission=submission
        )

        # 只有初审资格才算候选人：评审人与普通成员都不在内。
        # 当前持有人也被排除，换人表单再把他单独加回候选，好让下拉看得出现在是谁。
        self.assertEqual(set(candidates.values_list("pk", flat=True)), {spare.pk})

    def test_admin_offers_the_dropdown_for_a_pending_preliminary(self):
        submission = self._open_round()
        preliminary = preliminary_review_of(submission)
        other = make_preliminary_reviewer("preliminary-spare")
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("admin:reviews_preliminaryreview_change", args=(preliminary.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="reviewer"')
        candidates = set(
            response.context["adminform"]
            .form.fields["reviewer"]
            .queryset.values_list("pk", flat=True)
        )
        # 当前初审人留着（否则下拉看不出现在是谁），另一位可选。
        self.assertEqual(candidates, {preliminary.reviewer_id, other.pk})

    def test_admin_change_page_is_read_only_for_a_completed_preliminary(self):
        submission = self._open_round()
        preliminary = preliminary_review_of(submission)
        self._pass_preliminary(submission)
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("admin:reviews_preliminaryreview_change", args=(preliminary.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="reviewer"')

    def test_admin_swaps_the_preliminary_reviewer(self):
        submission = self._open_round()
        preliminary = preliminary_review_of(submission)
        other = make_preliminary_reviewer("preliminary-spare")
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("admin:reviews_preliminaryreview_change", args=(preliminary.pk,)),
            {"reviewer": other.pk, "_save": "保存"},
        )

        self.assertEqual(response.status_code, 302)
        preliminary.refresh_from_db()
        self.assertEqual(preliminary.reviewer, other)
        self.assertTrue(
            AuditLog.objects.filter(action="reviews.preliminary.reassign").exists()
        )

    def test_a_view_only_staff_account_cannot_swap_the_holder(self):
        """状态允许不等于有权改：只有查看权限的后台账号不能改派。"""
        submission = self._open_round()
        preliminary = preliminary_review_of(submission)
        other = make_preliminary_reviewer("preliminary-spare")
        viewer = make_user("preliminary-viewer", is_staff=True)
        viewer.user_permissions.add(
            Permission.objects.get(codename="view_preliminaryreview")
        )
        url = reverse("admin:reviews_preliminaryreview_change", args=(preliminary.pk,))
        self.client.force_login(viewer)

        # 看得到，但只能是只读的一页。
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'name="reviewer"')

        response = self.client.post(url, {"reviewer": other.pk, "_save": "保存"})

        self.assertEqual(response.status_code, 403)
        preliminary.refresh_from_db()
        self.assertEqual(preliminary.reviewer, self.preliminary)

