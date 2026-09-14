"""Acceptance tests for journal-style project proposal review."""

import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from core.registry import get_entries_for_user
from projects.models import ProjectGroup

from .forms import ReviewForm
from .models import (
    REVIEW_TYPE_CHOICES,
    REVIEW_TYPE_COMPETITION_PROJECT,
    REVIEW_TYPE_INNOVATION_MIDTERM,
    REVIEW_TYPE_INNOVATION_START,
    REVIEWER_QUOTA,
    ArchivedProposal,
    ProjectSubmission,
    ReviewAssignment,
)
from .services import (
    ReviewError,
    _settle_submission,
    complete_review,
    submit_for_review,
)


User = get_user_model()
MEDIA_ROOT = tempfile.mkdtemp()

#: A round type needing two reviewers, so the historic two-reviewer assertions hold.
TWO_REVIEWER_TYPE = REVIEW_TYPE_INNOVATION_MIDTERM


def _pdf(name="proposal.pdf"):
    return SimpleUploadedFile(name, b"%PDF-1.4 test proposal", content_type="application/pdf")


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

    def _submit(self, review_type=TWO_REVIEWER_TYPE, message="申请开题。"):
        return submit_for_review(
            group=self.group,
            submitter=self.contact,
            review_type=review_type,
            message=message,
        )

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

    # --- registration of the reviewer operation entry -----------------------

    def test_review_entry_visible_only_to_reviewers(self):
        reviewer_keys = {entry.key for entry in get_entries_for_user(self.reviewer_one)}
        member_keys = {entry.key for entry in get_entries_for_user(self.member)}

        self.assertIn("reviews.queue", reviewer_keys)
        self.assertNotIn("reviews.queue", member_keys)

    # --- submission ----------------------------------------------------------

    def test_submission_assigns_two_random_reviewers(self):
        submission = self._submit()

        self.assertEqual(submission.round, 1)
        self.assertEqual(submission.status, ProjectSubmission.PENDING)
        self.assertEqual(submission.assignments.count(), 2)
        self.assertEqual(
            set(submission.assignments.values_list("reviewer_id", flat=True)),
            {self.reviewer_one.pk, self.reviewer_two.pk},
        )

    def test_review_type_determines_reviewer_quota(self):
        self._make_reviewer("reviewer-three")

        for review_type, expected in REVIEWER_QUOTA.items():
            with self.subTest(review_type=review_type):
                submission = self._submit(review_type=review_type)

                self.assertEqual(submission.required_reviewers, expected)
                self.assertEqual(submission.assignments.count(), expected)

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

    def test_submission_blocked_when_candidates_below_quota(self):
        # Only two qualified reviewers exist, but a competition round needs three.
        with self.assertRaises(ReviewError) as caught:
            self._submit(review_type=REVIEW_TYPE_COMPETITION_PROJECT)

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
        self.assertNotContains(response, "reviewer-one")
        self.assertNotContains(response, "reviewer-two")

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
        self.client.force_login(self.contact)
        submit_response = self.client.post(
            reverse("projects:group_submit_review", args=(self.group.pk,)),
            {"review_type": TWO_REVIEWER_TYPE, "message": "申请参加竞赛。"},
        )
        self.assertEqual(submit_response.status_code, 302)

        submission = ProjectSubmission.objects.get(group=self.group)
        self.assertEqual(submission.review_type, TWO_REVIEWER_TYPE)
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

    def test_submit_view_requires_a_review_type(self):
        self.client.force_login(self.contact)

        response = self.client.post(
            reverse("projects:group_submit_review", args=(self.group.pk,)),
            {"message": "忘了选类型。"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(ProjectSubmission.objects.exists())

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
