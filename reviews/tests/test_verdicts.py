"""结论汇总与批注版：评审人交卷之后发生的事。

「全员通过才算通过」「需修改就打回」「批注版随通过归档且只归档一次」都在这
里；下载入口的权限也归这一块，因为它们是同一批文件的出口。
"""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from ..forms import ReviewForm
from ..models import (
    REVIEW_TYPE_INNOVATION_START,
    ArchivedProposal,
    ProjectSubmission,
    ReviewAssignment,
)
from ..services import (
    ReviewError,
    _settle_submission,
    complete_review,
)
from .base import ReviewTestCase
from .factories import (
    make_admin,
    make_group,
    make_preliminary_reviewer,
    make_reviewer,
    make_user,
    pdf,
)


class VerdictTests(ReviewTestCase):
    def setUp(self):
        self.admin = make_admin("review-admin")
        self.contact = make_user("review-contact")
        self.member = make_user("review-member")
        self.reviewer_one = make_reviewer("reviewer-one")
        self.reviewer_two = make_reviewer("reviewer-two")
        self.preliminary = make_preliminary_reviewer("preliminary-one")
        self.outsider = make_user("review-outsider")
        self.group = make_group("评审项目组", leader=self.contact, members=[self.member])

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
            reviewer_one=pdf("annotated-one.pdf"),
            reviewer_two=pdf("annotated-two.pdf"),
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

        self._approve_both(submission, reviewer_one=pdf("reviewer-one-批注.pdf"))

        record = ArchivedProposal.objects.get(submission=submission)
        self.assertTrue(record.file.name.endswith(".pdf"))
        self.assertNotIn("reviewer-one", record.file.name)
        self.assertNotIn("批注", record.file.name)

    def test_only_uploaders_produce_archive_entries(self):
        submission = self._submit()

        self._approve_both(submission, reviewer_one=pdf("annotated.pdf"))

        record = ArchivedProposal.objects.get(submission=submission)
        self.assertEqual(
            record.source_assignment,
            self._assignment(submission, self.reviewer_one),
        )

    def test_archive_is_idempotent(self):
        submission = self._submit()
        self._approve_both(submission, reviewer_one=pdf("annotated.pdf"))

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
            annotated_file=pdf("annotated.pdf"),
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

    def test_annotated_download_honours_group_visibility(self):
        submission = self._submit()
        assignment = self._assignment(submission, self.reviewer_one)
        complete_review(
            assignment=assignment,
            reviewer=self.reviewer_one,
            decision=ReviewAssignment.APPROVE,
            comment="已批注。",
            annotated_file=pdf("annotated.pdf"),
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
        self._approve_both(submission, reviewer_one=pdf("annotated.pdf"))
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
        self._approve_both(submission, reviewer_one=pdf("annotated.pdf"))
        self.client.force_login(self.member)

        response = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["archived_proposals"]), 1)
