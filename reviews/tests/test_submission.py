"""送审这一侧：进入「评审」的入口，以及「这一轮开不开得出来」。

开轮次的条件全在这里：送审类型、项目书、初审人够不够、评审人够不够（容量预检）、
上一轮结束没有。评审人怎么抽、结论怎么汇总、页面怎么渲染在别的模块。
"""

from django.urls import reverse

from core.registry import get_entries_for_user

from ..models import (
    REVIEWER_QUOTA,
    REVIEW_TYPE_CHOICES,
    REVIEW_TYPE_COMPETITION_PROJECT,
    PreliminaryReview,
    ProjectSubmission,
    preliminary_review_of,
)
from ..services import ReviewError
from .base import (
    TWO_REVIEWER_TYPE,
    ReviewTestCase,
)
from .factories import (
    make_group,
    make_preliminary_reviewer,
    make_reviewer,
    make_user,
)


class SubmissionTests(ReviewTestCase):
    def setUp(self):
        self.contact = make_user("review-contact")
        self.member = make_user("review-member")
        self.reviewer_one = make_reviewer("reviewer-one")
        self.reviewer_two = make_reviewer("reviewer-two")
        self.preliminary = make_preliminary_reviewer("preliminary-one")
        self.group = make_group("评审项目组", leader=self.contact, members=[self.member])

    # --- registration of the reviewer operation entry -----------------------

    def test_review_entry_visible_only_to_reviewers(self):
        reviewer_keys = {entry.key for entry in get_entries_for_user(self.reviewer_one)}
        member_keys = {entry.key for entry in get_entries_for_user(self.member)}

        self.assertIn("reviews.queue", reviewer_keys)
        self.assertNotIn("reviews.queue", member_keys)

    # --- submission ----------------------------------------------------------

    def test_submission_opens_a_preliminary_stage_before_the_reviewers(self):
        """送审先落到初审人手里：这一轮此时还没有任何评审人。"""
        submission = self._open_round()

        self.assertEqual(submission.status, ProjectSubmission.PRELIMINARY_PENDING)
        self.assertEqual(submission.assignments.count(), 0)
        preliminary = preliminary_review_of(submission)
        self.assertIsNotNone(preliminary)
        self.assertEqual(preliminary.reviewer, self.preliminary)
        self.assertEqual(preliminary.status, PreliminaryReview.PENDING)
        # 需要的评审人数照旧由类型决定，只是要等初审通过才分配。
        self.assertEqual(submission.required_reviewers, 2)

    def test_submission_assigns_two_random_reviewers(self):
        submission = self._submit()

        self.assertEqual(submission.round, 1)
        self.assertEqual(submission.status, ProjectSubmission.PENDING)
        self.assertEqual(submission.assignments.count(), 2)
        self.assertEqual(
            set(submission.assignments.values_list("reviewer_id", flat=True)),
            {self.reviewer_one.pk, self.reviewer_two.pk},
        )
        preliminary = preliminary_review_of(submission)
        self.assertEqual(preliminary.status, PreliminaryReview.COMPLETED)
        self.assertEqual(preliminary.decision, PreliminaryReview.APPROVE)

    def test_review_type_determines_reviewer_quota(self):
        make_reviewer("reviewer-three")

        for review_type, expected in REVIEWER_QUOTA.items():
            with self.subTest(review_type=review_type):
                submission = self._submit(review_type=review_type)

                self.assertEqual(submission.required_reviewers, expected)
                self.assertEqual(submission.assignments.count(), expected)
                # 收尾，否则下一轮会被「本轮未结束」挡住。
                self._approve_round(submission)

    def test_a_new_round_is_blocked_while_the_previous_one_is_open(self):
        first = self._submit()

        with self.assertRaises(ReviewError) as caught:
            self._submit()

        self.assertIn(f"第 {first.round} 轮", str(caught.exception))
        self.assertEqual(ProjectSubmission.objects.filter(group=self.group).count(), 1)

    def test_a_new_round_is_blocked_while_the_previous_one_is_in_preliminary(self):
        """初审中也是「未结束」：这一轮还压在平台手上，不能再开一轮。"""
        first = self._open_round()

        with self.assertRaises(ReviewError) as caught:
            self._open_round()

        self.assertIn(f"第 {first.round} 轮", str(caught.exception))
        self.assertEqual(ProjectSubmission.objects.filter(group=self.group).count(), 1)

    def test_a_new_round_opens_once_the_previous_one_has_a_verdict(self):
        first = self._submit()
        self._approve_round(first)

        second = self._submit()

        self.assertEqual(second.round, first.round + 1)
        self.assertEqual(second.status, ProjectSubmission.PENDING)

    def test_a_new_round_opens_after_the_preliminary_bounces_it(self):
        first = self._open_round()
        self._pass_preliminary(
            first, decision=PreliminaryReview.REVISE, comment="请先补齐预算。"
        )
        first.refresh_from_db()
        self.assertEqual(first.status, ProjectSubmission.NEEDS_REVISION)

        second = self._open_round()

        self.assertEqual(second.round, first.round + 1)
        self.assertEqual(second.status, ProjectSubmission.PRELIMINARY_PENDING)

    def test_legacy_submission_without_type_defaults_to_two(self):
        """Rounds created before submission types existed keep the old rule."""
        legacy = ProjectSubmission.objects.create(
            group=self.group,
            round=9,
            review_type="",
            submitted_by=self.contact,
        )

        self.assertEqual(legacy.required_reviewers, 2)

    def test_submission_requires_a_valid_review_type(self):
        for review_type in ("", "not-a-type"):
            with self.subTest(review_type=review_type):
                with self.assertRaises(ReviewError):
                    self._submit(review_type=review_type)

    def test_submission_requires_a_proposal(self):
        self.group.proposal.delete(save=True)

        with self.assertRaises(ReviewError):
            self._submit()

    def test_submission_blocked_when_no_preliminary_reviewer_is_available(self):
        self.preliminary.is_preliminary_reviewer = False
        self.preliminary.save(update_fields=["is_preliminary_reviewer"])

        with self.assertRaises(ReviewError) as caught:
            self._open_round()

        self.assertIn("初审人", str(caught.exception))
        self.assertFalse(ProjectSubmission.objects.exists())

    def test_submission_blocked_when_candidates_below_quota(self):
        """评审人不够就不开这一轮。

        抽人挪到了初审通过时，但「开得出一轮推进得了的送审」仍是提交这一侧的
        门槛：否则开出来的轮次谁也推进不了——联系人被单轮次约束挡住、初审人
        通不过，只能等管理员补资格或超级评审来收场。
        """
        # Only two qualified reviewers exist, but a competition round needs three.
        with self.assertRaises(ReviewError) as caught:
            self._open_round(review_type=REVIEW_TYPE_COMPETITION_PROJECT)

        self.assertIn("3 人", str(caught.exception))
        self.assertFalse(ProjectSubmission.objects.exists())

    def test_submit_view_requires_a_review_type(self):
        self.client.force_login(self.contact)

        response = self.client.post(
            reverse("projects:group_submit_review", args=(self.group.pk,)),
            {"message": "忘了选类型。"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(ProjectSubmission.objects.exists())

    def test_submit_view_refuses_while_a_round_is_still_open(self):
        first = self._submit()
        self.client.force_login(self.contact)

        response = self.client.post(
            reverse("projects:group_submit_review", args=(self.group.pk,)),
            {"review_type": TWO_REVIEWER_TYPE, "message": "再来一轮。"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(ProjectSubmission.objects.filter(group=self.group).count(), 1)
        self.assertEqual(
            ProjectSubmission.objects.get(group=self.group).round, first.round
        )



class ReviewTypeQuotaTests(ReviewTestCase):
    """The type → reviewer-count table is the single source of truth."""

    def test_quota_table_matches_the_agreed_rule(self):
        expected = {
            "competition_project": 3,
            "competition_provincial": 3,
            "competition_national": 3,
            "innovation_start": 1,
            "innovation_midterm": 2,
            "innovation_final": 2,
        }

        self.assertEqual(REVIEWER_QUOTA, expected)

    def test_every_choice_has_a_quota(self):
        for value, _label in REVIEW_TYPE_CHOICES:
            with self.subTest(review_type=value):
                self.assertIn(value, REVIEWER_QUOTA)


