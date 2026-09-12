"""Transactional project-proposal review operations.

Reviewer assignment and verdict aggregation live here so the rule "both
reviewers must approve" has exactly one implementation.
"""

import logging
import random

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from core.audit import record_audit

from .models import ProjectSubmission, ReviewAssignment


logger = logging.getLogger(__name__)
User = get_user_model()

REVIEWERS_PER_SUBMISSION = 2


class ReviewError(Exception):
    """A submission or review action violates a business rule."""


def _pick_reviewers(*, group, submitter):
    """Randomly pick reviewers, excluding the submitter and the group's members."""
    excluded = set(group.members.values_list("pk", flat=True))
    excluded.add(submitter.pk)
    candidates = list(
        User.objects.filter(is_reviewer=True, is_active=True).exclude(pk__in=excluded)
    )
    if len(candidates) < REVIEWERS_PER_SUBMISSION:
        raise ReviewError(
            f"当前可用的评审人不足 {REVIEWERS_PER_SUBMISSION} 人，无法提交审核。"
        )
    return random.sample(candidates, REVIEWERS_PER_SUBMISSION)


def submit_for_review(*, group, submitter, message="", request=None):
    """Open a new review round and assign reviewers to the group's proposal."""
    if not group.proposal:
        raise ReviewError("请先上传项目书，再提交审核。")
    reviewers = _pick_reviewers(group=group, submitter=submitter)

    with transaction.atomic():
        last = group.submissions.order_by("-round").first()
        round_number = (last.round + 1) if last else 1
        submission = ProjectSubmission.objects.create(
            group=group,
            round=round_number,
            message=message,
            submitted_by=submitter,
        )
        for reviewer in reviewers:
            ReviewAssignment.objects.create(submission=submission, reviewer=reviewer)

    record_audit(
        action="reviews.submission.create",
        user=submitter,
        target=submission,
        detail={
            "group_id": group.pk,
            "round": round_number,
            "reviewer_ids": [reviewer.pk for reviewer in reviewers],
        },
        request=request,
    )
    logger.info(
        "reviews.submission.create group_id=%s submission_id=%s round=%s reviewers=%s submitter=%s",
        group.pk,
        submission.pk,
        round_number,
        [reviewer.pk for reviewer in reviewers],
        submitter.get_username(),
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return submission


def complete_review(*, assignment, reviewer, decision, comment, request=None):
    """Record one reviewer's verdict and aggregate the submission status."""
    if assignment.reviewer_id != reviewer.pk:
        raise ReviewError("这不是分配给你的评审任务。")
    if decision not in dict(ReviewAssignment.DECISION_CHOICES):
        raise ReviewError("请选择评审决定。")

    with transaction.atomic():
        locked = (
            ReviewAssignment.objects.select_for_update()
            .select_related("submission")
            .get(pk=assignment.pk)
        )
        if locked.status == ReviewAssignment.COMPLETED:
            raise ReviewError("你已经完成过该评审。")
        locked.status = ReviewAssignment.COMPLETED
        locked.decision = decision
        locked.comment = comment
        locked.completed_at = timezone.now()
        locked.save(update_fields=["status", "decision", "comment", "completed_at"])

        submission = locked.submission
        if not submission.assignments.filter(status=ReviewAssignment.PENDING).exists():
            has_revision_request = submission.assignments.filter(
                decision=ReviewAssignment.REVISE
            ).exists()
            submission.status = (
                ProjectSubmission.NEEDS_REVISION
                if has_revision_request
                else ProjectSubmission.APPROVED
            )
            submission.decided_at = timezone.now()
            submission.save(update_fields=["status", "decided_at"])

    record_audit(
        action="reviews.assignment.complete",
        user=reviewer,
        target=locked,
        detail={
            "submission_id": locked.submission_id,
            "decision": decision,
            "submission_status": locked.submission.status,
        },
        request=request,
    )
    logger.info(
        "reviews.assignment.complete assignment_id=%s submission_id=%s decision=%s reviewer=%s",
        locked.pk,
        locked.submission_id,
        decision,
        reviewer.get_username(),
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return locked
