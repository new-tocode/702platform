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

from .models import ProjectSubmission, ReviewAssignment
from .services import ReviewError, complete_review, submit_for_review


User = get_user_model()
MEDIA_ROOT = tempfile.mkdtemp()


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

    def _submit(self):
        return submit_for_review(
            group=self.group,
            submitter=self.contact,
            message="申请开题。",
        )

    def _assignment(self, submission, reviewer):
        return submission.assignments.get(reviewer=reviewer)

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

    def test_submission_requires_a_proposal(self):
        self.group.proposal.delete(save=True)

        with self.assertRaises(ReviewError):
            self._submit()

    def test_submission_blocked_when_fewer_than_two_reviewers(self):
        self.reviewer_two.is_reviewer = False
        self.reviewer_two.save(update_fields=["is_reviewer"])

        with self.assertRaises(ReviewError):
            self._submit()

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

    def test_contact_submits_and_reviewer_completes_via_views(self):
        self.client.force_login(self.contact)
        submit_response = self.client.post(
            reverse("projects:group_submit_review", args=(self.group.pk,)),
            {"message": "申请参加竞赛。"},
        )
        self.assertEqual(submit_response.status_code, 302)

        submission = ProjectSubmission.objects.get(group=self.group)
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

    def test_proposal_upload_rejects_unsupported_extension(self):
        self.client.force_login(self.contact)

        response = self.client.post(
            reverse("projects:group_proposal_update", args=(self.group.pk,)),
            {"proposal": SimpleUploadedFile("plan.txt", b"hello", content_type="text/plain")},
        )

        self.assertEqual(response.status_code, 302)
        self.group.refresh_from_db()
        self.assertNotEqual(self.group.proposal.name, "plan.txt")
