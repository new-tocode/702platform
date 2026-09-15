"""Transactional project-proposal review operations.

Reviewer assignment, verdict aggregation and archiving live here so the rules
"a round needs as many reviewers as its type demands" and "every reviewer must
approve" each have exactly one implementation.
"""

import logging
import os
import random

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from core.audit import record_audit
from projects.models import ProjectGroup

from .models import (
    REVIEWER_QUOTA,
    ArchivedProposal,
    ProjectSubmission,
    ReviewAssignment,
    ReviewerLeave,
)


logger = logging.getLogger(__name__)
User = get_user_model()


class ReviewError(Exception):
    """A submission or review action violates a business rule."""


def eligible_reviewers(*, group, submitter, exclude_assigned_on=None):
    """Users who may take a review task for this group's proposal right now.

    The single definition of "who may review": the draw at submission time and
    an administrator's manual reassignment both come through here, so the
    exclusions (submitter, the group's members, anyone on leave) cannot drift
    apart between the two paths.
    """
    excluded = set(group.members.values_list("pk", flat=True))
    excluded.add(submitter.pk)
    if exclude_assigned_on is not None:
        excluded |= set(
            exclude_assigned_on.assignments.values_list("reviewer_id", flat=True)
        )
    on_leave = set(ReviewerLeave.objects.active().values_list("reviewer_id", flat=True))
    return (
        User.objects.filter(is_reviewer=True, is_active=True)
        .exclude(pk__in=excluded)
        .exclude(pk__in=on_leave)
    )


def _pick_reviewers(*, group, submitter, count):
    """Randomly draw reviewers for a brand-new round.

    Leave is honoured here, at draw time, rather than by flipping
    ``is_reviewer``: the qualification never changes, so nothing has to be
    restored when a leave window ends.
    """
    candidates = list(eligible_reviewers(group=group, submitter=submitter))
    if len(candidates) < count:
        # Only reached on the failure path, so the extra count is cheap here.
        on_leave = ReviewerLeave.objects.active().count()
        leave_note = f"（另有 {on_leave} 人请假）" if on_leave else ""
        raise ReviewError(
            f"当前可用的评审人不足 {count} 人{leave_note}，无法提交审核。"
        )
    return random.sample(candidates, count)


def submit_for_review(*, group, submitter, review_type, message="", request=None):
    """Open a new review round and assign the reviewers its type calls for."""
    if review_type not in REVIEWER_QUOTA:
        raise ReviewError("请选择评审类型。")
    if not group.proposal:
        raise ReviewError("请先上传项目书，再提交审核。")
    required = REVIEWER_QUOTA[review_type]

    with transaction.atomic():
        # Lock the group: without it, two submissions for the same group could
        # both pass the open-round check below and both compute the same next
        # round number, colliding on the (group, round) constraint.
        ProjectGroup.objects.select_for_update().get(pk=group.pk)
        open_round = (
            group.submissions.filter(status=ProjectSubmission.PENDING)
            .order_by("round")
            .first()
        )
        if open_round is not None:
            raise ReviewError(
                f"第 {open_round.round} 轮评审尚未结束，"
                "请等本轮出结论后再提交下一轮。"
            )

        reviewers = _pick_reviewers(group=group, submitter=submitter, count=required)
        last = group.submissions.order_by("-round").first()
        round_number = (last.round + 1) if last else 1
        submission = ProjectSubmission.objects.create(
            group=group,
            round=round_number,
            review_type=review_type,
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
            "review_type": review_type,
            "reviewer_ids": [reviewer.pk for reviewer in reviewers],
        },
        request=request,
    )
    logger.info(
        "reviews.submission.create group_id=%s submission_id=%s round=%s review_type=%s reviewers=%s submitter=%s",
        group.pk,
        submission.pk,
        round_number,
        review_type,
        [reviewer.pk for reviewer in reviewers],
        submitter.get_username(),
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return submission


def _archive_annotated_proposals(submission):
    """Copy every annotated proposal of an approved round into the archive.

    Reviewers who answered with text only leave no row: an archive entry
    without a file would carry no information. ``get_or_create`` plus the
    uniqueness on ``source_assignment`` keeps a retried aggregation idempotent.
    """
    annotated = submission.assignments.filter(
        status=ReviewAssignment.COMPLETED,
        decision=ReviewAssignment.APPROVE,
    ).exclude(annotated_file="")
    archived_count = 0
    for assignment in annotated:
        archived, created = ArchivedProposal.objects.get_or_create(
            source_assignment=assignment,
            defaults={"group": submission.group, "submission": submission},
        )
        if not created:
            continue
        archived.file.save(
            os.path.basename(assignment.annotated_file.name),
            assignment.annotated_file,
            save=True,
        )
        archived_count += 1
    if archived_count:
        logger.info(
            "reviews.proposal.archive submission_id=%s group_id=%s count=%s",
            submission.pk,
            submission.group_id,
            archived_count,
        )


def _settle_submission(submission):
    """Aggregate verdicts once every assignment is in, then archive if approved.

    The caller must already hold the submission row lock (see
    :func:`complete_review`): this reads the round's *other* assignments, so the
    parent row — not the reviewer's own assignment — is what serialises
    concurrent verdicts. A round that already reached a verdict is left alone,
    which also makes the archiving below idempotent.
    """
    if submission.status != ProjectSubmission.PENDING:
        return submission
    if submission.assignments.filter(status=ReviewAssignment.PENDING).exists():
        return submission

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

    if submission.status == ProjectSubmission.APPROVED:
        _archive_annotated_proposals(submission)
    return submission


def complete_review(
    *,
    assignment,
    reviewer,
    decision,
    comment,
    annotated_file=None,
    request=None,
):
    """Record one reviewer's verdict and aggregate the submission status."""
    if assignment.reviewer_id != reviewer.pk:
        raise ReviewError("这不是分配给你的评审任务。")
    if decision not in dict(ReviewAssignment.DECISION_CHOICES):
        raise ReviewError("请选择评审决定。")

    with transaction.atomic():
        # Lock the parent row first. The aggregation in _settle_submission reads
        # the round's other assignments, so locking only this assignment would
        # let two reviewers finishing at the same time each see the other as
        # still pending — and leave the round stuck at 评审中 forever. Lock order
        # is always submission → assignment.
        submission = ProjectSubmission.objects.select_for_update().get(
            pk=assignment.submission_id
        )
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
        update_fields = ["status", "decision", "comment", "completed_at"]
        if annotated_file is not None:
            locked.annotated_file = annotated_file
            update_fields.append("annotated_file")
        locked.save(update_fields=update_fields)

        _settle_submission(submission)

    record_audit(
        action="reviews.assignment.complete",
        user=reviewer,
        target=locked,
        detail={
            "submission_id": locked.submission_id,
            "decision": decision,
            "submission_status": submission.status,
            "annotated": annotated_file is not None,
        },
        request=request,
    )
    logger.info(
        "reviews.assignment.complete assignment_id=%s submission_id=%s decision=%s annotated=%s reviewer=%s",
        locked.pk,
        locked.submission_id,
        decision,
        annotated_file is not None,
        reviewer.get_username(),
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return locked


def reassign_reviewer(*, assignment, new_reviewer, actor, request=None):
    """Hand one pending review task to a different reviewer.

    Only a task that is still ``pending`` on a round that has not reached a
    verdict may be reassigned. Once a verdict exists the task is a record of who
    decided what: swapping the reviewer would re-attribute that decision (and
    its comment and annotated file) to somebody who never made it. Because the
    task stays pending, the round keeps the same number of open tasks, so
    nothing has to be re-aggregated and no archive is touched.

    The replaced reviewer's row is mutated rather than deleted, so the roster
    always shows exactly one task per (round, reviewer). Who held it before is
    kept in the audit log.
    """
    with transaction.atomic():
        # Same lock order as complete_review (submission → assignment): a
        # reviewer finishing concurrently would settle the round, after which
        # reassigning it would no longer be sound.
        submission = ProjectSubmission.objects.select_for_update().get(
            pk=assignment.submission_id
        )
        locked = (
            ReviewAssignment.objects.select_for_update()
            .select_related("submission__group", "submission__submitted_by")
            .get(pk=assignment.pk)
        )
        if locked.status != ReviewAssignment.PENDING:
            raise ReviewError("只有待评审的任务可以更换评审人。")
        if submission.status != ProjectSubmission.PENDING:
            raise ReviewError("该轮送审已给出结论，不能再更换评审人。")
        if locked.reviewer_id == new_reviewer.pk:
            raise ReviewError("评审人没有变化。")
        # The admin form limits the choices already; these checks are what make
        # the rule hold for any other caller too.
        if new_reviewer.pk == submission.submitted_by_id:
            raise ReviewError("提交人不能评审自己的项目书。")
        if submission.group.members.filter(pk=new_reviewer.pk).exists():
            raise ReviewError("该项目组成员不能评审本组的项目书。")
        if submission.assignments.filter(reviewer=new_reviewer).exists():
            raise ReviewError("该评审人已在本轮评审任务中。")
        if not eligible_reviewers(
            group=submission.group, submitter=submission.submitted_by
        ).filter(pk=new_reviewer.pk).exists():
            raise ReviewError("该账号当前不具备评审资格（可能已停用或正在请假）。")

        previous_reviewer_id = locked.reviewer_id
        locked.reviewer = new_reviewer
        locked.save(update_fields=["reviewer"])

    record_audit(
        action="reviews.assignment.reassign",
        user=actor,
        target=locked,
        detail={
            "submission_id": locked.submission_id,
            "from_reviewer_id": previous_reviewer_id,
            "to_reviewer_id": new_reviewer.pk,
        },
        request=request,
    )
    logger.info(
        "reviews.assignment.reassign assignment_id=%s submission_id=%s from_reviewer_id=%s to_reviewer_id=%s actor=%s",
        locked.pk,
        locked.submission_id,
        previous_reviewer_id,
        new_reviewer.pk,
        actor.get_username(),
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return locked


def count_pending_reviews(reviewer):
    """How many review tasks await this reviewer.

    Drives the platform's reminders (the post-login nudge and the member-centre
    todo card). Leave is deliberately not applied: taking leave does not excuse
    the reviews a reviewer already holds.
    """
    return ReviewAssignment.objects.filter(
        reviewer=reviewer,
        status=ReviewAssignment.PENDING,
    ).count()


def open_leave_for(reviewer, at=None):
    """The reviewer's not-yet-ended leave, if they have one."""
    return (
        ReviewerLeave.objects.filter(reviewer=reviewer)
        .open(at)
        .order_by("-starts_at", "-id")
        .first()
    )


def set_reviewer_leave(*, reviewer, starts_at, ends_at, reason="", actor, request=None):
    """Register or adjust the reviewer's open leave window.

    A reviewer holds at most one open window, so registering again edits that
    one instead of stacking a second. This is also how a reviewer or an
    administrator moves the recovery time earlier or later.
    """
    if not reviewer.is_reviewer:
        raise ReviewError("该账号没有评审资格，无需请假。")
    if ends_at <= starts_at:
        raise ReviewError("请假结束时间必须晚于开始时间。")
    if ends_at <= timezone.now():
        raise ReviewError("请假结束时间必须晚于当前时间。")

    with transaction.atomic():
        leave = (
            ReviewerLeave.objects.select_for_update()
            .filter(reviewer=reviewer)
            .open()
            .order_by("-starts_at", "-id")
            .first()
        )
        created = leave is None
        if created:
            leave = ReviewerLeave(reviewer=reviewer)
        leave.starts_at = starts_at
        leave.ends_at = ends_at
        leave.reason = reason
        leave.created_by = actor
        leave.save()

    record_audit(
        action="reviews.leave.set",
        user=actor,
        target=leave,
        detail={
            "reviewer_id": reviewer.pk,
            "created": created,
            "ends_at": ends_at.isoformat(),
        },
        request=request,
    )
    logger.info(
        "reviews.leave.set reviewer_id=%s leave_id=%s created=%s ends_at=%s actor=%s",
        reviewer.pk,
        leave.pk,
        created,
        ends_at.isoformat(),
        actor.get_username(),
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return leave


def clear_reviewer_leave(*, reviewer, actor, request=None):
    """Drop the reviewer's open leave window, restoring them immediately.

    Nothing restores eligibility because nothing ever removed it — deleting the
    window is the whole operation. The removal is kept in the audit log.
    """
    with transaction.atomic():
        open_leaves = ReviewerLeave.objects.select_for_update().filter(
            reviewer=reviewer
        ).open()
        removed = open_leaves.count()
        if removed:
            open_leaves.delete()

    if not removed:
        raise ReviewError("当前没有可取消的请假。")

    record_audit(
        action="reviews.leave.clear",
        user=actor,
        target=reviewer,
        detail={"reviewer_id": reviewer.pk, "removed": removed},
        request=request,
    )
    logger.info(
        "reviews.leave.clear reviewer_id=%s removed=%s actor=%s",
        reviewer.pk,
        removed,
        actor.get_username(),
        extra={"request_id": getattr(request, "request_id", "-")},
    )
