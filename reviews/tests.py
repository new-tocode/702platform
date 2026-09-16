"""Acceptance tests for journal-style project proposal review."""

import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog
from core.registry import get_entries_for_user
from projects.models import ProjectGroup
from projects.permissions import can_view_group

from .forms import (
    PreliminaryReviewForm,
    ReviewForm,
    ReviewerLeaveForm,
)
from .models import (
    REVIEW_TYPE_CHOICES,
    REVIEW_TYPE_COMPETITION_PROJECT,
    REVIEW_TYPE_INNOVATION_MIDTERM,
    REVIEW_TYPE_INNOVATION_START,
    REVIEWER_QUOTA,
    ArchivedProposal,
    PreliminaryReview,
    ProjectSubmission,
    ReviewAssignment,
    ReviewerLeave,
    preliminary_review_of,
)
from .services import (
    ReviewError,
    _settle_submission,
    can_override_review,
    clear_reviewer_leave,
    complete_preliminary_review,
    complete_review,
    count_pending_preliminary_reviews,
    count_pending_reviews,
    eligible_preliminary_reviewers,
    eligible_reviewers,
    override_blocker,
    override_review,
    reassign_preliminary_reviewer,
    reassign_reviewer,
    set_reviewer_leave,
    submit_for_review,
)


User = get_user_model()
MEDIA_ROOT = tempfile.mkdtemp()
LEAVE_MEDIA_ROOT = tempfile.mkdtemp()
REMINDER_MEDIA_ROOT = tempfile.mkdtemp()
SUPER_MEDIA_ROOT = tempfile.mkdtemp()
PRELIMINARY_MEDIA_ROOT = tempfile.mkdtemp()

#: A round type needing two reviewers, so the historic two-reviewer assertions hold.
TWO_REVIEWER_TYPE = REVIEW_TYPE_INNOVATION_MIDTERM


def _pdf(name="proposal.pdf"):
    return SimpleUploadedFile(name, b"%PDF-1.4 test proposal", content_type="application/pdf")


def _qualify(user, **flags):
    """Grant qualifications without the whole must-change-password dance."""
    for name, value in flags.items():
        setattr(user, name, value)
    user.must_change_password = False
    user.save(update_fields=[*flags, "must_change_password"])
    return user


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class ProjectReviewFlowTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="review-admin",
            password="Admin-Password-123!",
        )
        self.contact = User.objects.create_user(
            username="review-contact",
            password="Contact-Password-123!",
        )
        self.contact.must_change_password = False
        self.contact.save(update_fields=["must_change_password"])
        self.member = User.objects.create_user(
            username="review-member",
            password="Member-Password-123!",
        )
        self.member.must_change_password = False
        self.member.save(update_fields=["must_change_password"])
        self.reviewer_one = self._make_reviewer("reviewer-one")
        self.reviewer_two = self._make_reviewer("reviewer-two")
        self.preliminary = _qualify(
            User.objects.create_user(
                username="preliminary-one", password="Preliminary-Password-123!"
            ),
            is_preliminary_reviewer=True,
        )
        self.outsider = User.objects.create_user(
            username="review-outsider",
            password="Outsider-Password-123!",
        )
        self.outsider.must_change_password = False
        self.outsider.save(update_fields=["must_change_password"])

        self.group = ProjectGroup.objects.create(name="评审项目组", leader=self.contact)
        self.group.members.add(self.member)
        self.group.proposal.save("proposal.pdf", ContentFile(b"%PDF-1.4 proposal"), save=True)

    def _make_reviewer(self, username):
        user = User.objects.create_user(username=username, password="Reviewer-Password-123!")
        user.is_reviewer = True
        user.must_change_password = False
        user.save(update_fields=["is_reviewer", "must_change_password"])
        return user

    def _open_round(self, review_type=TWO_REVIEWER_TYPE, message="申请开题。"):
        """Submit a round and leave it in 初审中, as the group's own submit does."""
        return submit_for_review(
            group=self.group,
            submitter=self.contact,
            review_type=review_type,
            message=message,
        )

    def _pass_preliminary(
        self,
        submission,
        decision=PreliminaryReview.APPROVE,
        comment="同意送审。",
    ):
        """Answer the round's 初审: a 通过 is what draws the reviewers."""
        preliminary = submission.preliminary_review
        return complete_preliminary_review(
            preliminary=preliminary,
            reviewer=preliminary.reviewer,
            decision=decision,
            comment=comment,
        )

    def _submit(self, review_type=TWO_REVIEWER_TYPE, message="申请开题。"):
        """Submit a round and pass its 初审 — the round as a reviewer meets it."""
        submission = self._open_round(review_type=review_type, message=message)
        self._pass_preliminary(submission)
        submission.refresh_from_db()
        return submission

    def _assignment(self, submission, reviewer):
        return submission.assignments.get(reviewer=reviewer)

    def _approve_both(self, submission, **files):
        """Complete both assignments as approve; ``files`` maps reviewer to a file."""
        complete_review(
            assignment=self._assignment(submission, self.reviewer_one),
            reviewer=self.reviewer_one,
            decision=ReviewAssignment.APPROVE,
            comment="方案可行。",
            annotated_file=files.get("reviewer_one"),
        )
        complete_review(
            assignment=self._assignment(submission, self.reviewer_two),
            reviewer=self.reviewer_two,
            decision=ReviewAssignment.APPROVE,
            comment="同意开题。",
            annotated_file=files.get("reviewer_two"),
        )

    def _approve_round(self, submission):
        """Settle a round by approving every task, so the next round may open."""
        for assignment in submission.assignments.all():
            complete_review(
                assignment=assignment,
                reviewer=assignment.reviewer,
                decision=ReviewAssignment.APPROVE,
                comment="同意。",
            )

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
        self._make_reviewer("reviewer-three")

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

    # --- verdict aggregation -------------------------------------------------

    def test_both_approve_marks_submission_and_group_approved(self):
        submission = self._submit()

        complete_review(
            assignment=self._assignment(submission, self.reviewer_one),
            reviewer=self.reviewer_one,
            decision=ReviewAssignment.APPROVE,
            comment="方案可行。",
        )
        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.PENDING)

        complete_review(
            assignment=self._assignment(submission, self.reviewer_two),
            reviewer=self.reviewer_two,
            decision=ReviewAssignment.APPROVE,
            comment="同意开题。",
        )
        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.APPROVED)

    def test_single_reviewer_type_is_decided_by_one_verdict(self):
        submission = self._submit(review_type=REVIEW_TYPE_INNOVATION_START)

        self.assertEqual(submission.assignments.count(), 1)
        # Which of the two qualified reviewers is drawn is random.
        assignment = submission.assignments.get()
        complete_review(
            assignment=assignment,
            reviewer=assignment.reviewer,
            decision=ReviewAssignment.APPROVE,
            comment="同意立项。",
        )

        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.APPROVED)

    def test_one_revision_request_marks_needs_revision(self):
        submission = self._submit()

        complete_review(
            assignment=self._assignment(submission, self.reviewer_one),
            reviewer=self.reviewer_one,
            decision=ReviewAssignment.APPROVE,
            comment="可以。",
        )
        complete_review(
            assignment=self._assignment(submission, self.reviewer_two),
            reviewer=self.reviewer_two,
            decision=ReviewAssignment.REVISE,
            comment="请补充预算。",
        )
        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.NEEDS_REVISION)

    def test_settlement_reaches_a_verdict_from_any_caller(self):
        """Aggregation must not depend on which reviewer happens to finish last.

        The verdict is settled by whichever call finds no pending assignment, so
        settlement is reachable from any caller once the round is fully reviewed.
        """
        submission = self._submit()
        submission.assignments.update(
            status=ReviewAssignment.COMPLETED,
            decision=ReviewAssignment.APPROVE,
        )
        submission.refresh_from_db()

        _settle_submission(submission)

        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.APPROVED)

    def test_resubmission_creates_next_round(self):
        first = self._submit()
        complete_review(
            assignment=self._assignment(first, self.reviewer_one),
            reviewer=self.reviewer_one,
            decision=ReviewAssignment.REVISE,
            comment="修改后再来。",
        )
        complete_review(
            assignment=self._assignment(first, self.reviewer_two),
            reviewer=self.reviewer_two,
            decision=ReviewAssignment.REVISE,
            comment="同上。",
        )

        second = self._submit()

        self.assertEqual(second.round, 2)
        self.assertEqual(ProjectSubmission.objects.filter(group=self.group).count(), 2)

    def test_reviewer_cannot_complete_someone_elses_assignment(self):
        submission = self._submit()
        assignment = self._assignment(submission, self.reviewer_one)

        with self.assertRaises(ReviewError):
            complete_review(
                assignment=assignment,
                reviewer=self.reviewer_two,
                decision=ReviewAssignment.APPROVE,
                comment="越权。",
            )

    # --- annotated proposals and archiving -----------------------------------

    def test_annotated_file_is_optional(self):
        submission = self._submit()

        self._approve_both(submission)

        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.APPROVED)
        self.assertFalse(self._assignment(submission, self.reviewer_one).annotated_file)

    def test_approved_submission_archives_annotated_proposals(self):
        submission = self._submit()

        self._approve_both(
            submission,
            reviewer_one=_pdf("annotated-one.pdf"),
            reviewer_two=_pdf("annotated-two.pdf"),
        )

        archived = ArchivedProposal.objects.filter(submission=submission)
        self.assertEqual(archived.count(), 2)
        self.assertEqual(
            set(archived.values_list("source_assignment_id", flat=True)),
            set(submission.assignments.values_list("pk", flat=True)),
        )
        for record in archived:
            self.assertEqual(record.group_id, self.group.pk)
            self.assertTrue(record.file.name)

    def test_archive_filename_does_not_leak_the_reviewer(self):
        submission = self._submit()

        self._approve_both(submission, reviewer_one=_pdf("reviewer-one-批注.pdf"))

        record = ArchivedProposal.objects.get(submission=submission)
        self.assertTrue(record.file.name.endswith(".pdf"))
        self.assertNotIn("reviewer-one", record.file.name)
        self.assertNotIn("批注", record.file.name)

    def test_only_uploaders_produce_archive_entries(self):
        submission = self._submit()

        self._approve_both(submission, reviewer_one=_pdf("annotated.pdf"))

        record = ArchivedProposal.objects.get(submission=submission)
        self.assertEqual(
            record.source_assignment,
            self._assignment(submission, self.reviewer_one),
        )

    def test_archive_is_idempotent(self):
        submission = self._submit()
        self._approve_both(submission, reviewer_one=_pdf("annotated.pdf"))

        submission.refresh_from_db()
        _settle_submission(submission)

        self.assertEqual(ArchivedProposal.objects.filter(submission=submission).count(), 1)

    def test_needs_revision_does_not_archive(self):
        submission = self._submit()

        complete_review(
            assignment=self._assignment(submission, self.reviewer_one),
            reviewer=self.reviewer_one,
            decision=ReviewAssignment.APPROVE,
            comment="可以。",
            annotated_file=_pdf("annotated.pdf"),
        )
        complete_review(
            assignment=self._assignment(submission, self.reviewer_two),
            reviewer=self.reviewer_two,
            decision=ReviewAssignment.REVISE,
            comment="请补充预算。",
        )

        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.NEEDS_REVISION)
        self.assertFalse(ArchivedProposal.objects.filter(submission=submission).exists())
        # The annotated copy is still reachable on the assignment itself.
        self.assertTrue(
            self._assignment(submission, self.reviewer_one).annotated_file
        )

    def test_annotated_file_validator_rejects_unsupported_extension(self):
        form = ReviewForm(
            data={"decision": ReviewAssignment.APPROVE, "comment": "可以。"},
            files={"annotated_file": SimpleUploadedFile("notes.txt", b"hello")},
        )

        self.assertFalse(form.is_valid())
        self.assertIn("annotated_file", form.errors)

    # --- queue and detail views ---------------------------------------------

    def test_non_reviewer_cannot_open_review_queue(self):
        self.client.force_login(self.member)

        response = self.client.get(reverse("reviews:queue"))

        self.assertEqual(response.status_code, 403)

    def test_reviewer_sees_assigned_submission_and_can_enter_group_detail(self):
        submission = self._submit()
        self.client.force_login(self.reviewer_one)

        queue_response = self.client.get(reverse("reviews:queue"))
        detail_response = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )

        self.assertEqual(queue_response.status_code, 200)
        self.assertContains(queue_response, self.group.name)
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.context["my_assignment"].submission_id, submission.pk)

    def test_group_detail_is_hidden_from_unrelated_member(self):
        self._submit()
        self.client.force_login(self.outsider)

        response = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )

        self.assertEqual(response.status_code, 403)

    def test_group_member_can_view_review_history(self):
        submission = self._submit()
        complete_review(
            assignment=self._assignment(submission, self.reviewer_one),
            reviewer=self.reviewer_one,
            decision=ReviewAssignment.APPROVE,
            comment="同意。",
        )
        self.client.force_login(self.member)

        response = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "同意。")

    def test_reviewer_identity_is_hidden_on_group_detail(self):
        submission = self._submit()
        complete_review(
            assignment=self._assignment(submission, self.reviewer_one),
            reviewer=self.reviewer_one,
            decision=ReviewAssignment.APPROVE,
            comment="同意。",
        )
        self.client.force_login(self.member)

        response = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )

        self.assertContains(response, "评审人 1")
        self.assertContains(response, "初审")
        self.assertNotContains(response, "reviewer-one")
        self.assertNotContains(response, "reviewer-two")
        # 初审人同样匿名：页面上只写「初审」，不写账号。
        self.assertNotContains(response, "preliminary-one")

    def test_review_form_posts_multipart(self):
        """A browser only sends the annotated file if the form is multipart.

        The test client encodes files as multipart on its own, so without this
        assertion a missing enctype would only ever break in a real browser.
        """
        self._submit()
        self.client.force_login(self.reviewer_one)

        response = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )

        self.assertContains(response, 'enctype="multipart/form-data"')

    def test_contact_submits_and_reviewer_completes_via_views(self):
        """整条链路走视图：提交 → 初审 → 评审。"""
        self.client.force_login(self.contact)
        submit_response = self.client.post(
            reverse("projects:group_submit_review", args=(self.group.pk,)),
            {"review_type": TWO_REVIEWER_TYPE, "message": "申请参加竞赛。"},
        )
        self.assertEqual(submit_response.status_code, 302)

        submission = ProjectSubmission.objects.get(group=self.group)
        self.assertEqual(submission.review_type, TWO_REVIEWER_TYPE)
        self.assertEqual(submission.status, ProjectSubmission.PRELIMINARY_PENDING)

        preliminary = preliminary_review_of(submission)
        self.client.force_login(self.preliminary)
        preliminary_response = self.client.post(
            reverse("reviews:preliminary_complete", args=(preliminary.pk,)),
            {"decision": PreliminaryReview.APPROVE, "comment": "同意送审。"},
        )
        self.assertEqual(preliminary_response.status_code, 302)
        preliminary.refresh_from_db()
        self.assertEqual(preliminary.status, PreliminaryReview.COMPLETED)
        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.PENDING)

        assignment = self._assignment(submission, self.reviewer_one)
        self.client.force_login(self.reviewer_one)
        complete_response = self.client.post(
            reverse("reviews:complete", args=(assignment.pk,)),
            {"decision": ReviewAssignment.APPROVE, "comment": "通过。"},
        )

        self.assertEqual(complete_response.status_code, 302)
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, ReviewAssignment.COMPLETED)
        self.assertEqual(assignment.decision, ReviewAssignment.APPROVE)

    def test_group_manage_reports_the_preliminary_stage(self):
        """初审中同样是「本轮未结束」，措辞要说明在等谁。"""
        self._open_round()
        self.client.force_login(self.contact)

        response = self.client.get(
            reverse("projects:group_manage", args=(self.group.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "本轮未结束")
        self.assertContains(response, "初审中")
        self.assertNotContains(
            response, reverse("projects:group_submit_review", args=(self.group.pk,))
        )

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

    def test_group_manage_hides_the_submit_form_while_a_round_is_open(self):
        self._submit()
        self.client.force_login(self.contact)

        response = self.client.get(
            reverse("projects:group_manage", args=(self.group.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "本轮未结束")
        self.assertNotContains(
            response, reverse("projects:group_submit_review", args=(self.group.pk,))
        )

    def test_group_manage_offers_the_submit_form_when_nothing_is_open(self):
        self.client.force_login(self.contact)

        response = self.client.get(
            reverse("projects:group_manage", args=(self.group.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, reverse("projects:group_submit_review", args=(self.group.pk,))
        )

    def test_reviewer_uploads_annotated_file_via_view(self):
        submission = self._submit()
        assignment = self._assignment(submission, self.reviewer_one)
        self.client.force_login(self.reviewer_one)

        response = self.client.post(
            reverse("reviews:complete", args=(assignment.pk,)),
            {
                "decision": ReviewAssignment.APPROVE,
                "comment": "已在稿件上批注。",
                "annotated_file": _pdf("annotated.pdf"),
            },
        )

        self.assertEqual(response.status_code, 302)
        assignment.refresh_from_db()
        self.assertTrue(assignment.annotated_file)
        self.assertTrue(assignment.annotated_file.name.endswith(".pdf"))

    def test_annotated_download_honours_group_visibility(self):
        submission = self._submit()
        assignment = self._assignment(submission, self.reviewer_one)
        complete_review(
            assignment=assignment,
            reviewer=self.reviewer_one,
            decision=ReviewAssignment.APPROVE,
            comment="已批注。",
            annotated_file=_pdf("annotated.pdf"),
        )
        url = reverse("reviews:annotated", args=(assignment.pk,))

        for user in (self.member, self.admin, self.reviewer_one):
            with self.subTest(user=user.get_username()):
                self.client.force_login(user)
                self.assertEqual(self.client.get(url).status_code, 200)

        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_archived_proposal_download_honours_group_visibility(self):
        submission = self._submit()
        self._approve_both(submission, reviewer_one=_pdf("annotated.pdf"))
        record = ArchivedProposal.objects.get(submission=submission)
        url = reverse("reviews:archive_download", args=(record.pk,))

        for user in (self.member, self.admin):
            with self.subTest(user=user.get_username()):
                self.client.force_login(user)
                self.assertEqual(self.client.get(url).status_code, 200)

        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_group_detail_lists_archived_proposals(self):
        submission = self._submit()
        self._approve_both(submission, reviewer_one=_pdf("annotated.pdf"))
        self.client.force_login(self.member)

        response = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["archived_proposals"]), 1)

    def test_proposal_upload_rejects_unsupported_extension(self):
        self.client.force_login(self.contact)

        response = self.client.post(
            reverse("projects:group_proposal_update", args=(self.group.pk,)),
            {"proposal": SimpleUploadedFile("plan.txt", b"hello", content_type="text/plain")},
        )

        self.assertEqual(response.status_code, 302)
        self.group.refresh_from_db()
        self.assertNotEqual(self.group.proposal.name, "plan.txt")


class ReviewTypeQuotaTests(TestCase):
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


@override_settings(MEDIA_ROOT=LEAVE_MEDIA_ROOT)
class ReviewerLeaveTests(TestCase):
    """Review leave suspends new review requests for a window, then self-restores.

    Eligibility is never stored as a flag — it is derived from the window — so
    "恢复" needs no scheduled job. These tests pin that down.
    """

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(LEAVE_MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="leave-admin",
            password="Admin-Password-123!",
        )
        self.contact = User.objects.create_user(
            username="leave-contact",
            password="Contact-Password-123!",
        )
        self.contact.must_change_password = False
        self.contact.save(update_fields=["must_change_password"])
        self.reviewer = self._make_reviewer("leave-reviewer")
        self.preliminary = _qualify(
            User.objects.create_user(
                username="leave-preliminary", password="Preliminary-Password-123!"
            ),
            is_preliminary_reviewer=True,
        )
        self.member = User.objects.create_user(
            username="leave-member",
            password="Member-Password-123!",
        )
        self.member.must_change_password = False
        self.member.save(update_fields=["must_change_password"])

        self.group = ProjectGroup.objects.create(name="请假项目组", leader=self.contact)
        self.group.proposal.save(
            "proposal.pdf", ContentFile(b"%PDF-1.4 proposal"), save=True
        )

    def _make_reviewer(self, username):
        user = User.objects.create_user(
            username=username, password="Reviewer-Password-123!"
        )
        user.is_reviewer = True
        user.must_change_password = False
        user.save(update_fields=["is_reviewer", "must_change_password"])
        return user

    def _leave(self, *, reviewer=None, starts_in=-1, ends_in=7, reason=""):
        """Create a leave window relative to now, in days."""
        now = timezone.now()
        return ReviewerLeave.objects.create(
            reviewer=reviewer or self.reviewer,
            starts_at=now + timedelta(days=starts_in),
            ends_at=now + timedelta(days=ends_in),
            reason=reason,
        )

    def _open_round(self, review_type=REVIEW_TYPE_INNOVATION_START):
        """Submit a round and leave it in 初审中, before any reviewer is drawn."""
        return submit_for_review(
            group=self.group,
            submitter=self.contact,
            review_type=review_type,
        )

    def _pass_preliminary(self, submission):
        """Approve the round's 初审 — the moment the reviewers are drawn."""
        preliminary = submission.preliminary_review
        return complete_preliminary_review(
            preliminary=preliminary,
            reviewer=preliminary.reviewer,
            decision=PreliminaryReview.APPROVE,
            comment="同意送审。",
        )

    def _draw_one(self):
        """Submit a single-reviewer round; returns the drawn reviewer."""
        submission = self._open_round()
        self._pass_preliminary(submission)
        return submission.assignments.get().reviewer

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

    def test_covers_only_its_own_window(self):
        leave = self._leave(starts_in=-1, ends_in=2)

        self.assertTrue(leave.covers(leave.starts_at))
        self.assertTrue(leave.covers(leave.ends_at - timedelta(seconds=1)))
        self.assertFalse(leave.covers(leave.starts_at - timedelta(seconds=1)))
        # The end is exclusive: at ends_at the reviewer is back on duty.
        self.assertFalse(leave.covers(leave.ends_at))

    # --- effect on reviewer draws -------------------------------------------

    def test_reviewer_on_leave_is_not_drawn(self):
        other = self._make_reviewer("leave-reviewer-two")
        self._leave(starts_in=-1, ends_in=7)

        self.assertEqual(self._draw_one(), other)

    def test_expired_leave_restores_eligibility(self):
        """No job runs at ends_at — the reviewer is simply eligible again."""
        other = self._make_reviewer("leave-reviewer-two")
        self._leave(starts_in=-7, ends_in=-1)
        self._leave(reviewer=other, starts_in=-1, ends_in=7)

        self.assertEqual(self._draw_one(), self.reviewer)

    def test_leave_that_has_not_started_does_not_exclude_yet(self):
        other = self._make_reviewer("leave-reviewer-two")
        self._leave(starts_in=1, ends_in=7)
        self._leave(reviewer=other, starts_in=-1, ends_in=7)

        self.assertEqual(self._draw_one(), self.reviewer)

    def test_preliminary_reviewer_on_leave_is_not_drawn_for_preliminary(self):
        """请假窗口对初审同样生效：它说的是这个人现在不在，与任务种类无关。"""
        other = _qualify(
            User.objects.create_user(
                username="leave-preliminary-two", password="Preliminary-Password-123!"
            ),
            is_preliminary_reviewer=True,
        )
        self._leave(reviewer=self.preliminary, starts_in=-1, ends_in=7)

        drawn = self._open_round().preliminary_review.reviewer

        self.assertEqual(drawn, other)

    def test_shortage_message_mentions_how_many_are_on_leave(self):
        self._leave(starts_in=-1, ends_in=7)

        with self.assertRaises(ReviewError) as caught:
            self._open_round(review_type=REVIEW_TYPE_INNOVATION_MIDTERM)

        self.assertIn("另有 1 人请假", str(caught.exception))

    def test_the_leave_note_counts_only_accounts_holding_the_qualification(self):
        """提示里的「另有 N 人请假」只算得上的人：初审人请假与评审人缺口无关。"""
        # 另留一位初审人在岗，送审才走得到评审人这一步。
        _qualify(
            User.objects.create_user(
                username="leave-preliminary-two", password="Preliminary-Password-123!"
            ),
            is_preliminary_reviewer=True,
        )
        self._leave(reviewer=self.preliminary, starts_in=-1, ends_in=7)

        with self.assertRaises(ReviewError) as caught:
            self._open_round(review_type=REVIEW_TYPE_INNOVATION_MIDTERM)

        self.assertIn("评审人不足", str(caught.exception))
        self.assertNotIn("请假", str(caught.exception))

    def test_clearing_leave_restores_immediately(self):
        other = self._make_reviewer("leave-reviewer-two")
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


@override_settings(MEDIA_ROOT=REMINDER_MEDIA_ROOT)
class ReviewReminderTests(TestCase):
    """Unfinished reviews are surfaced twice: right after login, and on the member centre."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(REMINDER_MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.contact = User.objects.create_user(
            username="remind-contact",
            password="Contact-Password-123!",
        )
        self.contact.must_change_password = False
        self.contact.save(update_fields=["must_change_password"])
        self.reviewer = User.objects.create_user(
            username="remind-reviewer",
            password="Password-123!",
        )
        self.reviewer.is_reviewer = True
        self.reviewer.must_change_password = False
        self.reviewer.save(update_fields=["is_reviewer", "must_change_password"])
        self.preliminary = User.objects.create_user(
            username="remind-preliminary",
            password="Password-123!",
        )
        self.preliminary.is_preliminary_reviewer = True
        self.preliminary.must_change_password = False
        self.preliminary.save(
            update_fields=["is_preliminary_reviewer", "must_change_password"]
        )
        self.member = User.objects.create_user(
            username="remind-member",
            password="Password-123!",
        )
        self.member.must_change_password = False
        self.member.save(update_fields=["must_change_password"])

        self.group = ProjectGroup.objects.create(name="提醒项目组", leader=self.contact)
        self.group.proposal.save(
            "proposal.pdf", ContentFile(b"%PDF-1.4 proposal"), save=True
        )

    def _open_round(self, group=None):
        """Open a round that stays in 初审中, with no reviewer assigned yet."""
        return submit_for_review(
            group=group or self.group,
            submitter=self.contact,
            review_type=REVIEW_TYPE_INNOVATION_START,
        )

    def _submit_round(self, group=None):
        """Open a round and pass its 初审, leaving the reviewer one pending task."""
        submission = self._open_round(group=group)
        preliminary = submission.preliminary_review
        complete_preliminary_review(
            preliminary=preliminary,
            reviewer=preliminary.reviewer,
            decision=PreliminaryReview.APPROVE,
            comment="同意送审。",
        )
        return submission

    def _login(self, username):
        return self.client.post(
            reverse("accounts:login"),
            {"username": username, "password": "Password-123!"},
            follow=True,
        )

    # --- the count -----------------------------------------------------------

    def test_count_only_covers_pending_tasks(self):
        submission = self._submit_round()
        self.assertEqual(count_pending_reviews(self.reviewer), 1)

        complete_review(
            assignment=submission.assignments.get(),
            reviewer=self.reviewer,
            decision=ReviewAssignment.APPROVE,
            comment="同意。",
        )

        self.assertEqual(count_pending_reviews(self.reviewer), 0)

    def test_count_accumulates_across_groups(self):
        """同一名评审人可能同时持有来自不同项目组的待评审任务。"""
        other_group = ProjectGroup.objects.create(
            name="提醒项目组二", leader=self.contact
        )
        other_group.proposal.save(
            "proposal.pdf", ContentFile(b"%PDF-1.4 proposal"), save=True
        )

        self._submit_round()
        self._submit_round(group=other_group)

        self.assertEqual(count_pending_reviews(self.reviewer), 2)

    def test_preliminary_count_only_covers_pending_preliminary_tasks(self):
        submission = self._open_round()
        self.assertEqual(count_pending_preliminary_reviews(self.preliminary), 1)

        self.assertIsNotNone(submission.preliminary_review)
        PreliminaryReview.objects.filter(submission=submission).update(
            status=PreliminaryReview.RELEASED
        )

        self.assertEqual(count_pending_preliminary_reviews(self.preliminary), 0)

    # --- the login nudge -----------------------------------------------------

    def test_login_reminds_a_reviewer_holding_pending_tasks(self):
        self._submit_round()

        response = self._login(self.reviewer.username)

        self.assertContains(response, "1 份项目书待评审")

    def test_login_stays_quiet_without_pending_tasks(self):
        response = self._login(self.reviewer.username)

        self.assertNotContains(response, "份项目书待评审")

    def test_login_stays_quiet_after_the_qualification_is_revoked(self):
        """Reminding someone who can no longer open the queue would mislead them."""
        self._submit_round()
        self.reviewer.is_reviewer = False
        self.reviewer.save(update_fields=["is_reviewer"])

        response = self._login(self.reviewer.username)

        self.assertNotContains(response, "份项目书待评审")

    def test_login_stays_quiet_for_a_plain_member(self):
        self._submit_round()

        response = self._login(self.member.username)

        self.assertNotContains(response, "份项目书待评审")

    def test_login_reminds_a_preliminary_reviewer_too(self):
        self._open_round()

        response = self._login(self.preliminary.username)

        self.assertContains(response, "1 份项目书待初审")

    def test_login_names_both_kinds_of_pending_task(self):
        """同一个人两种任务都有时，提醒要把两个数字分开说。"""
        both = User.objects.create_user(username="remind-both", password="Password-123!")
        both.is_reviewer = True
        both.is_preliminary_reviewer = True
        both.must_change_password = False
        both.save(
            update_fields=["is_reviewer", "is_preliminary_reviewer", "must_change_password"]
        )
        other_group = ProjectGroup.objects.create(
            name="提醒项目组二", leader=self.contact
        )
        other_group.proposal.save(
            "proposal.pdf", ContentFile(b"%PDF-1.4 proposal"), save=True
        )
        review_round = self._submit_round()
        preliminary_round = self._open_round(group=other_group)
        # 把两条任务都记到这个账号名下：两种资格都具备的人，手上有两种任务。
        ReviewAssignment.objects.filter(submission=review_round).update(reviewer=both)
        PreliminaryReview.objects.filter(submission=preliminary_round).update(
            reviewer=both
        )

        response = self._login("remind-both")

        self.assertContains(response, "1 份项目书待初审")
        self.assertContains(response, "1 份项目书待评审")

    # --- the member-centre todo card -----------------------------------------

    def test_member_home_shows_a_todo_card_with_the_count(self):
        self._submit_round()
        self.client.force_login(self.reviewer)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertEqual(response.context["pending_review_count"], 1)
        self.assertContains(response, "份项目书待你评审")
        self.assertContains(response, '<span class="n">1</span>')

    def test_member_home_shows_no_todo_card_when_nothing_is_pending(self):
        self.client.force_login(self.reviewer)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertEqual(response.context["pending_review_count"], 0)
        self.assertNotContains(response, "份项目书待你评审")

    def test_member_home_counts_preliminary_tasks_of_their_own(self):
        self._open_round()
        self.client.force_login(self.preliminary)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertEqual(response.context["pending_preliminary_count"], 1)
        self.assertEqual(response.context["pending_review_count"], 0)
        self.assertContains(response, "份项目书待你初审")
        self.assertContains(response, '<span class="n">1</span>')

    def test_member_home_shows_no_todo_card_for_non_reviewers(self):
        self.client.force_login(self.member)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertNotIn("pending_review_count", response.context)
        self.assertNotContains(response, "份项目书待你评审")


class ReviewAssignmentReassignmentTests(TestCase):
    """An administrator can hand a still-pending task to a different reviewer.

    This is the only recovery path for a round whose reviewer went quiet or
    turned out to have a conflict of interest — without it such a round sits at
    评审中 forever. Verdicts are never rewritten, so the permission is limited to
    tasks that are pending on a round that has not been decided.
    """

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="swap-admin",
            password="Admin-Password-123!",
        )
        self.contact = User.objects.create_user(
            username="swap-contact",
            password="Contact-Password-123!",
        )
        self.contact.must_change_password = False
        self.contact.save(update_fields=["must_change_password"])
        self.member = User.objects.create_user(
            username="swap-member",
            password="Member-Password-123!",
        )
        self.member.must_change_password = False
        self.member.save(update_fields=["must_change_password"])
        self.outsider = User.objects.create_user(
            username="swap-outsider",
            password="Outsider-Password-123!",
        )
        self.outsider.must_change_password = False
        self.outsider.save(update_fields=["must_change_password"])
        self.reviewers = [
            self._make_reviewer(name)
            for name in ("swap-reviewer-one", "swap-reviewer-two", "swap-reviewer-three")
        ]
        self.preliminary = _qualify(
            User.objects.create_user(
                username="swap-preliminary", password="Preliminary-Password-123!"
            ),
            is_preliminary_reviewer=True,
        )

        self.group = ProjectGroup.objects.create(name="换人项目组", leader=self.contact)
        self.group.members.add(self.member)
        # 本类只关心「有一份项目书」这个事实，不读文件内容，所以不落盘。
        self.group.proposal.name = "project_proposals/existing.pdf"
        self.group.save(update_fields=["proposal"])

    def _make_reviewer(self, username):
        user = User.objects.create_user(
            username=username, password="Reviewer-Password-123!"
        )
        user.is_reviewer = True
        user.must_change_password = False
        user.save(update_fields=["is_reviewer", "must_change_password"])
        return user

    def _submit(self):
        """Two-reviewer round, leaving one of the three reviewers spare."""
        submission = submit_for_review(
            group=self.group,
            submitter=self.contact,
            review_type=REVIEW_TYPE_INNOVATION_MIDTERM,
        )
        preliminary = submission.preliminary_review
        complete_preliminary_review(
            preliminary=preliminary,
            reviewer=preliminary.reviewer,
            decision=PreliminaryReview.APPROVE,
            comment="同意送审。",
        )
        return submission

    def _spare_reviewer(self, submission):
        assigned = set(submission.assignments.values_list("reviewer_id", flat=True))
        return next(user for user in self.reviewers if user.pk not in assigned)

    def _change_url(self, assignment):
        return reverse(
            "admin:reviews_reviewassignment_change", args=(assignment.pk,)
        )

    # --- the service ---------------------------------------------------------

    def test_swapping_moves_the_task_to_the_new_reviewer(self):
        submission = self._submit()
        assignment = submission.assignments.first()
        spare = self._spare_reviewer(submission)

        reassign_reviewer(assignment=assignment, new_reviewer=spare, actor=self.admin)

        assignment.refresh_from_db()
        self.assertEqual(assignment.reviewer, spare)
        # 换人不改变任务数与状态，因此无需重新判结论。
        self.assertEqual(assignment.status, ReviewAssignment.PENDING)
        self.assertEqual(submission.assignments.count(), 2)
        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.PENDING)
        audit = AuditLog.objects.get(action="reviews.assignment.reassign")
        self.assertEqual(audit.detail["to_reviewer_id"], spare.pk)

    def test_a_completed_task_cannot_be_swapped(self):
        submission = self._submit()
        assignment = submission.assignments.first()
        complete_review(
            assignment=assignment,
            reviewer=assignment.reviewer,
            decision=ReviewAssignment.APPROVE,
            comment="同意。",
        )
        assignment.refresh_from_db()
        spare = self._spare_reviewer(submission)

        with self.assertRaises(ReviewError):
            reassign_reviewer(assignment=assignment, new_reviewer=spare, actor=self.admin)

        assignment.refresh_from_db()
        self.assertNotEqual(assignment.reviewer, spare)
        # 已经落下的结论、意见不能被换人改写。
        self.assertEqual(assignment.comment, "同意。")

    def test_a_round_that_already_has_a_verdict_cannot_be_swapped(self):
        """Guards an abnormal state:正常流程下判结论的前提就是没有待评审任务。"""
        submission = self._submit()
        assignment = submission.assignments.first()
        spare = self._spare_reviewer(submission)
        ProjectSubmission.objects.filter(pk=submission.pk).update(
            status=ProjectSubmission.APPROVED
        )

        with self.assertRaises(ReviewError):
            reassign_reviewer(assignment=assignment, new_reviewer=spare, actor=self.admin)

    def test_the_current_reviewer_is_not_a_change(self):
        submission = self._submit()
        assignment = submission.assignments.first()

        with self.assertRaises(ReviewError):
            reassign_reviewer(
                assignment=assignment,
                new_reviewer=assignment.reviewer,
                actor=self.admin,
            )

    def test_the_submitter_cannot_be_swapped_in(self):
        submission = self._submit()
        assignment = submission.assignments.first()

        with self.assertRaises(ReviewError):
            reassign_reviewer(
                assignment=assignment, new_reviewer=self.contact, actor=self.admin
            )

    def test_a_group_member_cannot_be_swapped_in(self):
        submission = self._submit()
        assignment = submission.assignments.first()
        self.member.is_reviewer = True
        self.member.save(update_fields=["is_reviewer"])

        with self.assertRaises(ReviewError):
            reassign_reviewer(
                assignment=assignment, new_reviewer=self.member, actor=self.admin
            )

    def test_someone_already_on_the_round_cannot_be_swapped_in(self):
        submission = self._submit()
        assignment = submission.assignments.first()
        other = submission.assignments.exclude(pk=assignment.pk).get().reviewer

        with self.assertRaises(ReviewError):
            reassign_reviewer(
                assignment=assignment, new_reviewer=other, actor=self.admin
            )

    def test_a_non_reviewer_cannot_be_swapped_in(self):
        submission = self._submit()
        assignment = submission.assignments.first()

        with self.assertRaises(ReviewError):
            reassign_reviewer(
                assignment=assignment, new_reviewer=self.outsider, actor=self.admin
            )

    def test_an_inactive_reviewer_cannot_be_swapped_in(self):
        submission = self._submit()
        assignment = submission.assignments.first()
        spare = self._spare_reviewer(submission)
        spare.is_active = False
        spare.save(update_fields=["is_active"])

        with self.assertRaises(ReviewError):
            reassign_reviewer(assignment=assignment, new_reviewer=spare, actor=self.admin)

    def test_a_reviewer_on_leave_cannot_be_swapped_in(self):
        submission = self._submit()
        assignment = submission.assignments.first()
        spare = self._spare_reviewer(submission)
        now = timezone.now()
        ReviewerLeave.objects.create(
            reviewer=spare,
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=7),
        )

        with self.assertRaises(ReviewError):
            reassign_reviewer(assignment=assignment, new_reviewer=spare, actor=self.admin)

    def test_the_rounds_preliminary_reviewer_cannot_be_swapped_in(self):
        """一个人既初审又评审时，也不接自己初审通过的那一轮。"""
        submission = self._submit()
        assignment = submission.assignments.first()
        self.preliminary.is_reviewer = True
        self.preliminary.save(update_fields=["is_reviewer"])

        with self.assertRaises(ReviewError):
            reassign_reviewer(
                assignment=assignment,
                new_reviewer=self.preliminary,
                actor=self.admin,
            )

        # 候选名单同样不包含他。
        candidates = eligible_reviewers(
            group=self.group, submitter=self.contact, submission=submission
        )
        self.assertNotIn(self.preliminary, candidates)

    # --- the admin change page ----------------------------------------------

    def test_admin_offers_the_reviewer_dropdown_for_a_pending_task(self):
        submission = self._submit()
        assignment = submission.assignments.first()
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
        assignment = submission.assignments.first()
        complete_review(
            assignment=assignment,
            reviewer=assignment.reviewer,
            decision=ReviewAssignment.APPROVE,
            comment="同意。",
        )
        self.client.force_login(self.admin)

        response = self.client.get(self._change_url(assignment))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="reviewer"')

    def test_admin_swaps_the_reviewer(self):
        submission = self._submit()
        assignment = submission.assignments.first()
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
        assignment = submission.assignments.first()
        complete_review(
            assignment=assignment,
            reviewer=assignment.reviewer,
            decision=ReviewAssignment.APPROVE,
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
        assignment = submission.assignments.first()
        original_reviewer_id = assignment.reviewer_id
        spare = self._spare_reviewer(submission)
        viewer = _qualify(
            User.objects.create_user(
                username="swap-viewer", password="Viewer-Password-123!"
            ),
        )
        viewer.is_staff = True
        viewer.save(update_fields=["is_staff"])
        viewer.user_permissions.add(
            Permission.objects.get(codename="view_reviewassignment")
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
        assignment = submission.assignments.first()
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("admin:reviews_reviewassignment_delete", args=(assignment.pk,))
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(ReviewAssignment.objects.filter(pk=assignment.pk).exists())


@override_settings(MEDIA_ROOT=SUPER_MEDIA_ROOT)
class SuperReviewerOverrideTests(TestCase):
    """A super reviewer settles an in-progress round with one vote.

    The point of the role is to be able to decide a round that is stuck or
    contested, so the verdict must not be re-derived from the ordinary
    reviewers' votes — an earlier 需修改 must not overrule it.
    """

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(SUPER_MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.contact = User.objects.create_user(
            username="super-contact", password="Contact-Password-123!"
        )
        self.contact.must_change_password = False
        self.contact.save(update_fields=["must_change_password"])
        self.member = User.objects.create_user(
            username="super-member", password="Member-Password-123!"
        )
        self.member.must_change_password = False
        self.member.save(update_fields=["must_change_password"])
        self.reviewer_one = self._make_user("super-reviewer-one", is_reviewer=True)
        self.reviewer_two = self._make_user("super-reviewer-two", is_reviewer=True)
        # Only the override qualification — never drawn as an ordinary reviewer.
        self.super_reviewer = self._make_user("super-boss", is_super_reviewer=True)
        self.preliminary = self._make_user(
            "super-preliminary", is_preliminary_reviewer=True
        )
        self.outsider = self._make_user("super-outsider")

        self.group = ProjectGroup.objects.create(name="超级评审项目组", leader=self.contact)
        self.group.members.add(self.member)
        self.group.proposal.save(
            "proposal.pdf", ContentFile(b"%PDF-1.4 proposal"), save=True
        )

    def _make_user(
        self,
        username,
        is_reviewer=False,
        is_super_reviewer=False,
        is_preliminary_reviewer=False,
    ):
        user = User.objects.create_user(username=username, password="Password-123!")
        user.is_reviewer = is_reviewer
        user.is_super_reviewer = is_super_reviewer
        user.is_preliminary_reviewer = is_preliminary_reviewer
        user.must_change_password = False
        user.save(
            update_fields=[
                "is_reviewer",
                "is_super_reviewer",
                "is_preliminary_reviewer",
                "must_change_password",
            ]
        )
        return user

    def _open_round(self):
        """Submit a round and leave it in 初审中, with no reviewers assigned."""
        return submit_for_review(
            group=self.group,
            submitter=self.contact,
            review_type=REVIEW_TYPE_INNOVATION_MIDTERM,
        )

    def _submit(self):
        """Submit a round and let its 初审 through, so the reviewers are drawn."""
        submission = self._open_round()
        preliminary = submission.preliminary_review
        complete_preliminary_review(
            preliminary=preliminary,
            reviewer=preliminary.reviewer,
            decision=PreliminaryReview.APPROVE,
            comment="同意送审。",
        )
        return submission

    def _override(self, submission, decision=ReviewAssignment.APPROVE, **kwargs):
        kwargs.setdefault("comment", "超级评审意见。")
        return override_review(
            submission=submission,
            super_reviewer=kwargs.pop("super_reviewer", self.super_reviewer),
            decision=decision,
            **kwargs,
        )

    # --- the vote settles the round -----------------------------------------

    def test_override_approves_the_round_and_releases_the_waiting_reviewers(self):
        submission = self._submit()

        self._override(submission)

        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.APPROVED)
        self.assertIsNotNone(submission.decided_at)
        self.assertEqual(
            set(submission.assignments.values_list("status", flat=True)),
            {ReviewAssignment.RELEASED, ReviewAssignment.COMPLETED},
        )
        override_row = submission.assignments.get(is_override=True)
        self.assertEqual(override_row.reviewer, self.super_reviewer)
        self.assertEqual(override_row.decision, ReviewAssignment.APPROVE)
        self.assertEqual(override_row.status, ReviewAssignment.COMPLETED)
        audit = AuditLog.objects.get(action="reviews.submission.override")
        self.assertEqual(audit.detail["released"], 2)

    def test_override_rejects_the_round(self):
        submission = self._submit()

        self._override(submission, decision=ReviewAssignment.REVISE)

        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.NEEDS_REVISION)
        self.assertEqual(
            submission.assignments.filter(status=ReviewAssignment.RELEASED).count(), 2
        )
        self.assertFalse(ArchivedProposal.objects.filter(submission=submission).exists())

    def test_override_beats_an_earlier_revision_request(self):
        """The super vote must not be re-derived from the ordinary reviewers' votes."""
        submission = self._submit()
        first = submission.assignments.filter(reviewer=self.reviewer_one).get()
        complete_review(
            assignment=first,
            reviewer=self.reviewer_one,
            decision=ReviewAssignment.REVISE,
            comment="请补充预算。",
        )

        self._override(submission)

        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.APPROVED)

    def test_override_archives_every_annotated_copy(self):
        submission = self._submit()
        complete_review(
            assignment=submission.assignments.filter(reviewer=self.reviewer_one).get(),
            reviewer=self.reviewer_one,
            decision=ReviewAssignment.APPROVE,
            comment="同意。",
            annotated_file=_pdf("reviewer-one.pdf"),
        )

        self._override(submission, annotated_file=_pdf("super.pdf"))

        archived = ArchivedProposal.objects.filter(submission=submission)
        self.assertEqual(archived.count(), 2)
        # 归档的正是「已完成且通过」的那两条；被释放的那条没有批注文件，不产生归档。
        self.assertEqual(
            set(archived.values_list("source_assignment_id", flat=True)),
            set(
                submission.assignments.filter(
                    status=ReviewAssignment.COMPLETED,
                    decision=ReviewAssignment.APPROVE,
                ).values_list("pk", flat=True)
            ),
        )

    # --- the released reviewer cannot come back ------------------------------

    def test_a_released_task_can_no_longer_be_submitted(self):
        submission = self._submit()
        released = submission.assignments.filter(reviewer=self.reviewer_two).get()

        self._override(submission)

        with self.assertRaises(ReviewError):
            complete_review(
                assignment=released,
                reviewer=self.reviewer_two,
                decision=ReviewAssignment.APPROVE,
                comment="我还是评一下。",
            )
        released.refresh_from_db()
        self.assertEqual(released.status, ReviewAssignment.RELEASED)

    def test_released_tasks_drop_out_of_the_reminder_count(self):
        submission = self._submit()
        self.assertEqual(count_pending_reviews(self.reviewer_one), 1)

        self._override(submission)

        self.assertEqual(count_pending_reviews(self.reviewer_one), 0)

    # --- the override reaches a round waiting on its 初审 ----------------------

    def test_override_settles_a_round_still_in_preliminary(self):
        """初审中也是「进行中」：初审人失联时，超级评审照样能敲定该轮。"""
        submission = self._open_round()

        self._override(submission)

        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.APPROVED)
        preliminary = preliminary_review_of(submission)
        self.assertEqual(preliminary.status, PreliminaryReview.RELEASED)
        self.assertEqual(count_pending_preliminary_reviews(self.preliminary), 0)
        # 这一轮还没分配过评审人，所以被释放的只有那条初审任务。
        self.assertFalse(submission.assignments.filter(is_override=False).exists())
        audit = AuditLog.objects.get(action="reviews.submission.override")
        self.assertEqual(audit.detail["released"], 0)
        self.assertEqual(audit.detail["released_preliminary"], 1)

    def test_a_released_preliminary_can_no_longer_be_submitted(self):
        submission = self._open_round()
        preliminary = submission.preliminary_review

        self._override(submission)

        with self.assertRaises(ReviewError):
            complete_preliminary_review(
                preliminary=preliminary,
                reviewer=self.preliminary,
                decision=PreliminaryReview.APPROVE,
                comment="我还是审一下。",
            )
        preliminary.refresh_from_db()
        self.assertEqual(preliminary.status, PreliminaryReview.RELEASED)

    def test_a_super_reviewer_who_is_also_the_rounds_preliminary_cannot_override_it(self):
        """同一个人不能既放行又敲定同一轮：两票都是他一个人的意见。"""
        submission = self._open_round()
        self.preliminary.is_super_reviewer = True
        self.preliminary.save(update_fields=["is_super_reviewer"])

        self.assertEqual(
            override_blocker(submission=submission, user=self.preliminary),
            "你在本轮有初审任务，请直接提交那一条",
        )
        with self.assertRaises(ReviewError):
            self._override(submission, super_reviewer=self.preliminary)

    def test_the_released_preliminary_shows_up_in_its_holders_queue(self):
        """被敲定不是凭空消失：初审人的队列里要看得到这一条已释放。"""
        submission = self._open_round()

        self._override(submission)

        self.client.force_login(self.preliminary)
        response = self.client.get(reverse("reviews:queue"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "已释放的初审")
        self.assertContains(response, self.group.name)
        self.assertEqual(
            [row.submission_id for row in response.context["preliminary_released"]],
            [submission.pk],
        )

    def test_a_super_reviewer_keeps_the_access_its_own_vote_earned(self):
        """资格并存时授权取并集：敲定之后仍看得到自己投过票的组。"""
        submission = self._submit()

        self._override(submission)

        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.APPROVED)
        self.assertTrue(can_view_group(self.super_reviewer, self.group))

    # --- who may not override ------------------------------------------------

    def test_a_super_reviewer_holding_a_task_on_the_round_cannot_override_it(self):
        submission = self._submit()
        ReviewAssignment.objects.create(
            submission=submission, reviewer=self.super_reviewer
        )

        self.assertFalse(
            can_override_review(submission=submission, user=self.super_reviewer)
        )
        with self.assertRaises(ReviewError):
            self._override(submission)

    def test_a_plain_reviewer_cannot_override(self):
        submission = self._submit()

        self.assertFalse(
            can_override_review(submission=submission, user=self.reviewer_one)
        )
        with self.assertRaises(ReviewError):
            self._override(submission, super_reviewer=self.reviewer_one)

    def test_the_submitter_cannot_override(self):
        submission = self._submit()
        self.contact.is_super_reviewer = True
        self.contact.save(update_fields=["is_super_reviewer"])

        with self.assertRaises(ReviewError):
            self._override(submission, super_reviewer=self.contact)

    def test_a_group_member_cannot_override(self):
        submission = self._submit()
        self.member.is_super_reviewer = True
        self.member.save(update_fields=["is_super_reviewer"])

        with self.assertRaises(ReviewError):
            self._override(submission, super_reviewer=self.member)

    def test_a_settled_round_cannot_be_overridden(self):
        submission = self._submit()
        for assignment in submission.assignments.all():
            complete_review(
                assignment=assignment,
                reviewer=assignment.reviewer,
                decision=ReviewAssignment.APPROVE,
                comment="同意。",
            )

        with self.assertRaises(ReviewError):
            self._override(submission, decision=ReviewAssignment.REVISE)

    # --- reach: queue and group visibility -----------------------------------

    def test_the_review_entry_is_visible_to_super_reviewers(self):
        keys = {entry.key for entry in get_entries_for_user(self.super_reviewer)}

        self.assertIn("reviews.queue", keys)

    def test_super_reviewer_sees_a_group_only_while_it_has_an_open_round(self):
        self.assertFalse(can_view_group(self.super_reviewer, self.group))
        submission = self._open_round()
        # 初审中也算进行中：要看项目书才谈得上敲定。
        self.assertTrue(can_view_group(self.super_reviewer, self.group))
        preliminary = submission.preliminary_review
        complete_preliminary_review(
            preliminary=preliminary,
            reviewer=preliminary.reviewer,
            decision=PreliminaryReview.APPROVE,
            comment="同意送审。",
        )
        self.assertTrue(can_view_group(self.super_reviewer, self.group))

        for assignment in submission.assignments.all():
            complete_review(
                assignment=assignment,
                reviewer=assignment.reviewer,
                decision=ReviewAssignment.APPROVE,
                comment="同意。",
            )

        self.assertFalse(can_view_group(self.super_reviewer, self.group))

    def test_queue_lists_a_round_waiting_on_its_preliminary(self):
        submission = self._open_round()
        self.client.force_login(self.super_reviewer)

        response = self.client.get(reverse("reviews:queue"))

        self.assertContains(response, "初审中")
        rows = response.context["open_rounds"]
        self.assertEqual([row["submission"].pk for row in rows], [submission.pk])
        # 这一轮尚未分配评审人，超级评审可以行使（不标注「不可行使」）。
        self.assertIsNone(rows[0]["blocker"])

    def test_queue_lists_every_open_round_for_a_super_reviewer(self):
        other = ProjectGroup.objects.create(name="另一个组", leader=self.contact)
        other.proposal.save("proposal.pdf", ContentFile(b"%PDF-1.4 p"), save=True)
        self._submit()
        submit_for_review(
            group=other,
            submitter=self.contact,
            review_type=REVIEW_TYPE_INNOVATION_START,
        )
        self.client.force_login(self.super_reviewer)

        response = self.client.get(reverse("reviews:queue"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "全部进行中")
        self.assertContains(response, "超级评审项目组")
        self.assertContains(response, "另一个组")
        self.assertEqual(len(response.context["open_rounds"]), 2)
        # 这条账号两条都能行使，所以给的是可操作按钮、没有「不可行使」标注。
        self.assertContains(response, "查看项目书并决定")
        self.assertNotContains(response, "不可行使")

    def test_queue_explains_why_a_round_cannot_be_overridden(self):
        """无权行使时不要把按钮写成「并决定」——那是在承诺做不到的事。"""
        submission = self._submit()
        self.contact.is_super_reviewer = True
        self.contact.save(update_fields=["is_super_reviewer"])
        self.client.force_login(self.contact)

        response = self.client.get(reverse("reviews:queue"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "不可行使")
        self.assertContains(response, "你是本轮的提交人")
        self.assertNotContains(response, "查看项目书并决定")
        rows = response.context["open_rounds"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["submission"].pk, submission.pk)
        self.assertEqual(rows[0]["blocker"], "你是本轮的提交人")

    def test_override_blocker_names_each_reason(self):
        submission = self._submit()

        self.assertIsNone(
            override_blocker(submission=submission, user=self.super_reviewer)
        )
        self.assertEqual(
            override_blocker(submission=submission, user=self.reviewer_one),
            "没有超级评审资格",
        )
        self.contact.is_super_reviewer = True
        self.contact.save(update_fields=["is_super_reviewer"])
        self.assertEqual(
            override_blocker(submission=submission, user=self.contact),
            "你是本轮的提交人",
        )
        self.member.is_super_reviewer = True
        self.member.save(update_fields=["is_super_reviewer"])
        self.assertEqual(
            override_blocker(submission=submission, user=self.member),
            "你是本项目组成员",
        )
        ReviewAssignment.objects.create(
            submission=submission, reviewer=self.super_reviewer
        )
        self.assertEqual(
            override_blocker(submission=submission, user=self.super_reviewer),
            "你在本轮已有评审任务，请直接提交那一条",
        )
        self.preliminary.is_super_reviewer = True
        self.preliminary.save(update_fields=["is_super_reviewer"])
        self.assertEqual(
            override_blocker(submission=submission, user=self.preliminary),
            "你是本轮的初审人，已经就该轮给出初审意见",
        )

    def test_queue_has_no_open_rounds_section_for_a_plain_reviewer(self):
        self._submit()
        self.client.force_login(self.reviewer_one)

        response = self.client.get(reverse("reviews:queue"))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("open_rounds", response.context)
        self.assertNotContains(response, "全部进行中")

    # --- the views -----------------------------------------------------------

    def test_super_reviewer_overrides_via_view(self):
        submission = self._submit()
        self.client.force_login(self.super_reviewer)

        response = self.client.post(
            reverse("reviews:override", args=(submission.pk,)),
            {"override-decision": ReviewAssignment.APPROVE, "override-comment": "同意。"},
        )

        self.assertEqual(response.status_code, 302)
        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.APPROVED)

    def test_override_view_requires_a_comment(self):
        submission = self._submit()
        self.client.force_login(self.super_reviewer)

        response = self.client.post(
            reverse("reviews:override", args=(submission.pk,)),
            {"override-decision": ReviewAssignment.APPROVE, "override-comment": ""},
        )

        self.assertEqual(response.status_code, 302)
        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.PENDING)

    def test_override_view_rejects_plain_reviewers_and_get(self):
        submission = self._submit()
        url = reverse("reviews:override", args=(submission.pk,))
        self.client.force_login(self.reviewer_one)
        self.assertEqual(
            self.client.post(url, {"override-decision": "approve", "override-comment": "x"}).status_code,
            403,
        )

        self.client.force_login(self.super_reviewer)
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_group_detail_offers_the_override_form_only_to_super_reviewers(self):
        submission = self._submit()
        url = reverse("projects:group_detail", args=(self.group.pk,))

        self.client.force_login(self.reviewer_one)
        plain = self.client.get(url)
        self.assertNotContains(plain, "一票决定")
        self.assertFalse(plain.context["can_override"])

        self.client.force_login(self.super_reviewer)
        boss = self.client.get(url)
        self.assertContains(boss, "一票决定")
        self.assertTrue(boss.context["can_override"])
        self.assertEqual(
            boss.context["latest_submission"].pk, submission.pk
        )

    def test_group_detail_shows_a_released_task_as_released(self):
        submission = self._submit()
        self._override(submission)
        self.client.force_login(self.member)

        response = self.client.get(reverse("projects:group_detail", args=(self.group.pk,)))

        self.assertContains(response, "已释放")
        self.assertContains(response, "超级评审")
        # 超级评审同样匿名：页面上不出现其账号。
        self.assertNotContains(response, self.super_reviewer.username)

    # --- markup stays well formed -------------------------------------------

    def test_queue_markup_stays_balanced(self):
        """Django 模板不校验 HTML 嵌套：区块对了但标签没配平照样渲染 200。"""
        submission = self._submit()
        self.client.force_login(self.super_reviewer)

        with_open_rounds = self.client.get(reverse("reviews:queue"))
        self._override(submission)
        with_released = self.client.get(reverse("reviews:queue"))
        # 初审人那一侧的面板（待初审 / 已完成的初审）另走一趟。
        self.client.force_login(self.preliminary)
        preliminary_side = self.client.get(reverse("reviews:queue"))

        for response in (with_open_rounds, with_released, preliminary_side):
            html = response.content.decode()
            self.assertEqual(html.count("<div"), html.count("</div>"))

    def test_group_detail_markup_stays_balanced(self):
        submission = self._submit()
        self.client.force_login(self.super_reviewer)

        with_reviewers = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )
        self._override(submission)
        settled = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )
        # 再开一轮、停在初审中：初审人的「我的初审」面板也渲染一遍。
        self._open_round()
        self.client.force_login(self.preliminary)
        in_preliminary = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )

        for response in (with_reviewers, settled, in_preliminary):
            html = response.content.decode()
            self.assertEqual(html.count("<div"), html.count("</div>"))


class AdminRoundDeletionTests(TestCase):
    """A round is deleted as a whole, together with its review tasks.

    ``ReviewAssignmentAdmin`` still refuses to delete a single task — that would
    silently change how many reviewers the round needs. But that guard also used
    to make the round undeletable, because Django asks the task's admin about the
    tasks a round deletion would carry away. The two rules must coexist: whole
    rounds go, individual tasks stay.
    """

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="del-admin", password="Admin-Password-123!"
        )
        self.contact = User.objects.create_user(
            username="del-contact", password="Contact-Password-123!"
        )
        self.contact.must_change_password = False
        self.contact.save(update_fields=["must_change_password"])
        self.reviewers = [
            self._make_reviewer(name) for name in ("del-reviewer-one", "del-reviewer-two")
        ]
        self.preliminary = _qualify(
            User.objects.create_user(
                username="del-preliminary", password="Preliminary-Password-123!"
            ),
            is_preliminary_reviewer=True,
        )

        self.group = ProjectGroup.objects.create(name="删除项目组", leader=self.contact)
        # 只需要「有项目书」这一事实，不读文件内容，所以不落盘。
        self.group.proposal.name = "project_proposals/existing.pdf"
        self.group.save(update_fields=["proposal"])

    def _make_reviewer(self, username):
        user = User.objects.create_user(
            username=username, password="Reviewer-Password-123!"
        )
        user.is_reviewer = True
        user.must_change_password = False
        user.save(update_fields=["is_reviewer", "must_change_password"])
        return user

    def _open_round(self):
        """Submit a round and leave it in 初审中, with no reviewers assigned."""
        return submit_for_review(
            group=self.group,
            submitter=self.contact,
            review_type=REVIEW_TYPE_INNOVATION_MIDTERM,
        )

    def _submit(self):
        submission = self._open_round()
        preliminary = submission.preliminary_review
        complete_preliminary_review(
            preliminary=preliminary,
            reviewer=preliminary.reviewer,
            decision=PreliminaryReview.APPROVE,
            comment="同意送审。",
        )
        return submission

    def _delete_url(self, submission):
        return reverse(
            "admin:reviews_projectsubmission_delete", args=(submission.pk,)
        )

    def test_admin_deletes_a_round_together_with_its_tasks(self):
        submission = self._submit()
        submission_pk = submission.pk
        assignment_pks = list(submission.assignments.values_list("pk", flat=True))
        preliminary_pk = submission.preliminary_review.pk
        self.client.force_login(self.admin)

        response = self.client.post(self._delete_url(submission), {"post": "yes"})

        self.assertEqual(response.status_code, 302)
        self.assertFalse(ProjectSubmission.objects.filter(pk=submission_pk).exists())
        self.assertFalse(ReviewAssignment.objects.filter(pk__in=assignment_pks).exists())
        self.assertFalse(PreliminaryReview.objects.filter(pk=preliminary_pk).exists())
        audit = AuditLog.objects.get(action="reviews.submission.delete")
        self.assertEqual(audit.detail["submission_id"], submission_pk)
        self.assertEqual(audit.detail["assignments"], 2)
        self.assertEqual(audit.detail["preliminary"], 1)

    def test_admin_deletes_a_round_still_in_preliminary(self):
        """初审同样是整轮的一部分：删掉的轮次不会留下孤儿初审任务。"""
        submission = self._open_round()
        submission_pk = submission.pk
        preliminary_pk = submission.preliminary_review.pk
        self.client.force_login(self.admin)

        response = self.client.post(self._delete_url(submission), {"post": "yes"})

        self.assertEqual(response.status_code, 302)
        self.assertFalse(ProjectSubmission.objects.filter(pk=submission_pk).exists())
        self.assertFalse(PreliminaryReview.objects.filter(pk=preliminary_pk).exists())
        audit = AuditLog.objects.get(action="reviews.submission.delete")
        self.assertEqual(audit.detail["assignments"], 0)
        self.assertEqual(audit.detail["preliminary"], 1)

    def test_admin_deletion_is_refused_once_the_round_is_archived(self):
        submission = self._submit()
        ArchivedProposal.objects.create(
            group=self.group,
            submission=submission,
            source_assignment=submission.assignments.first(),
            file="review_archives/kept.pdf",
        )
        submission_pk = submission.pk
        self.client.force_login(self.admin)

        response = self.client.post(self._delete_url(submission), {"post": "yes"})

        # PROTECT 拦住级联：确认页被重新渲染，对象仍在。
        self.assertEqual(response.status_code, 200)
        self.assertTrue(ProjectSubmission.objects.filter(pk=submission_pk).exists())

    def test_the_single_task_guard_stays_closed(self):
        """删整轮放开的同时，单独删一条任务仍然被拒。"""
        submission = self._submit()
        assignment = submission.assignments.first()

        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("admin:reviews_reviewassignment_delete", args=(assignment.pk,))
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(ReviewAssignment.objects.filter(pk=assignment.pk).exists())

    def test_the_single_preliminary_guard_stays_closed(self):
        """初审任务也一样：单独删掉它会让这一轮再也进不去评审。"""
        submission = self._open_round()
        preliminary = submission.preliminary_review

        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("admin:reviews_preliminaryreview_delete", args=(preliminary.pk,))
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(PreliminaryReview.objects.filter(pk=preliminary.pk).exists())


@override_settings(MEDIA_ROOT=PRELIMINARY_MEDIA_ROOT)
class PreliminaryReviewTests(TestCase):
    """送审先过初审人这一关，通过后才抽评审人。

    初审是「关卡」而不是评审团：只有一个位置（一对一）、只有与评审同一对结论
    （通过 / 需修改），而且通过它的那个人不会再被抽进这一轮的评审人里——一个人
    既放行又评审，等于让同一份意见在一轮里占两个位置。
    """

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(PRELIMINARY_MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="preliminary-admin",
            password="Admin-Password-123!",
        )
        self.contact = User.objects.create_user(
            username="preliminary-contact",
            password="Contact-Password-123!",
        )
        self.contact.must_change_password = False
        self.contact.save(update_fields=["must_change_password"])
        self.member = User.objects.create_user(
            username="preliminary-member",
            password="Member-Password-123!",
        )
        self.member.must_change_password = False
        self.member.save(update_fields=["must_change_password"])
        # 只放一位初审人在岗：抽签结果确定，断言才写得住。
        self.preliminary = self._make_preliminary("preliminary-one")
        self.reviewer_one = self._make_reviewer("preliminary-reviewer-one")
        self.reviewer_two = self._make_reviewer("preliminary-reviewer-two")
        self.outsider = User.objects.create_user(
            username="preliminary-outsider",
            password="Outsider-Password-123!",
        )
        self.outsider.must_change_password = False
        self.outsider.save(update_fields=["must_change_password"])

        self.group = ProjectGroup.objects.create(name="初审项目组", leader=self.contact)
        self.group.members.add(self.member)
        self.group.proposal.save(
            "proposal.pdf", ContentFile(b"%PDF-1.4 proposal"), save=True
        )

    def _make_preliminary(self, username):
        return _qualify(
            User.objects.create_user(
                username=username, password="Preliminary-Password-123!"
            ),
            is_preliminary_reviewer=True,
        )

    def _make_reviewer(self, username):
        return _qualify(
            User.objects.create_user(username=username, password="Reviewer-Password-123!"),
            is_reviewer=True,
        )

    def _open_round(self, review_type=REVIEW_TYPE_INNOVATION_MIDTERM, message="申请开题。"):
        """Submit a round and leave it in 初审中."""
        return submit_for_review(
            group=self.group,
            submitter=self.contact,
            review_type=review_type,
            message=message,
        )

    def _answer(
        self,
        submission,
        decision=PreliminaryReview.APPROVE,
        comment="同意送审。",
    ):
        """Answer the round's 初审 as whoever holds it."""
        preliminary = preliminary_review_of(submission)
        return complete_preliminary_review(
            preliminary=preliminary,
            reviewer=preliminary.reviewer,
            decision=decision,
            comment=comment,
        )

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

        self._answer(submission)

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
            self._answer(submission)

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
        self._answer(submission)

        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.PENDING)
        self.assertEqual(submission.assignments.count(), 2)

    def test_a_revision_request_ends_the_round_without_reviewers(self):
        submission = self._open_round()

        self._answer(
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

        self._answer(submission)

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

        self._answer(submission)

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
        self._answer(submission)

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
        other = self._make_preliminary("preliminary-other")

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
        self._answer(
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
        self._answer(submission)
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
        other = self._make_preliminary("preliminary-other")
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
        other = self._make_preliminary("preliminary-spare")

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

    def test_a_completed_preliminary_cannot_be_swapped(self):
        submission = self._open_round()
        preliminary = preliminary_review_of(submission)
        self._answer(submission)
        other = self._make_preliminary("preliminary-spare")

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
        _qualify(self.contact, is_preliminary_reviewer=True)
        _qualify(self.member, is_preliminary_reviewer=True)

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
        other = self._make_preliminary("preliminary-spare")
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
        spare = self._make_preliminary("preliminary-spare")

        candidates = eligible_preliminary_reviewers(
            group=self.group, submitter=self.contact, submission=submission
        )

        # 只有初审资格才算候选人：评审人与普通成员都不在内。
        # 当前持有人也被排除，换人表单再把他单独加回候选，好让下拉看得出现在是谁。
        self.assertEqual(set(candidates.values_list("pk", flat=True)), {spare.pk})

    def test_admin_offers_the_dropdown_for_a_pending_preliminary(self):
        submission = self._open_round()
        preliminary = preliminary_review_of(submission)
        other = self._make_preliminary("preliminary-spare")
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
        self._answer(submission)
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("admin:reviews_preliminaryreview_change", args=(preliminary.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="reviewer"')

    def test_admin_swaps_the_preliminary_reviewer(self):
        submission = self._open_round()
        preliminary = preliminary_review_of(submission)
        other = self._make_preliminary("preliminary-spare")
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
        other = self._make_preliminary("preliminary-spare")
        viewer = _qualify(
            User.objects.create_user(
                username="preliminary-viewer", password="Viewer-Password-123!"
            ),
        )
        viewer.is_staff = True
        viewer.save(update_fields=["is_staff"])
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

