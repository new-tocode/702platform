"""Transactional project-proposal review operations.

Reviewer assignment, verdict aggregation and archiving live here so the rules
"a round needs as many reviewers as its type demands" and "every reviewer must
approve" each have exactly one implementation.

A round has two stages. It is submitted to exactly one 初审人
(:class:`~reviews.models.PreliminaryReview`); their 通过 is what draws the
ordinary reviewers, so the "who may review" exclusions in
:func:`_eligible_pool` are shared by both draws instead of written twice.
"""

import logging
import os
import random

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from core.audit import record_audit
from projects.models import ProjectGroup
from projects.permissions import is_super_reviewer

from .models import (
    REVIEWER_QUOTA,
    ArchivedProposal,
    PreliminaryReview,
    ProjectSubmission,
    ReviewAssignment,
    ReviewerLeave,
    preliminary_review_of,
)


logger = logging.getLogger(__name__)
User = get_user_model()


class ReviewError(Exception):
    """A submission or review action violates a business rule."""


#: 两道关卡各自的资格口径。抽人和"够不够"的提示都问这里，不再各写一份。
REVIEWER_QUALIFICATION = {"is_reviewer": True}
PRELIMINARY_QUALIFICATION = {"is_preliminary_reviewer": True}


def _eligible_pool(*, group, submitter, qualification, submission=None):
    """Accounts that may take a task of this kind on this group's proposal now.

    The single definition of "who may review", shared by every draw and by an
    administrator's manual reassignment, so the exclusions cannot drift apart
    between them:

    * the submitter and the group's members (conflict of interest),
    * anyone on leave (their window covers both kinds of task),
    * whoever already holds a task on this round, including its 初审人 —
      a 初审人 who passed a round is not drawn as one of its reviewers, since
      letting one person both open and judge the same round hands their single
      opinion two slots in it.
    """
    excluded = set(group.members.values_list("pk", flat=True))
    excluded.add(submitter.pk)
    if submission is not None:
        excluded |= set(
            submission.assignments.values_list("reviewer_id", flat=True)
        )
        preliminary = preliminary_review_of(submission)
        if preliminary is not None:
            excluded.add(preliminary.reviewer_id)
    on_leave = set(ReviewerLeave.objects.active().values_list("reviewer_id", flat=True))
    return (
        User.objects.filter(is_active=True, **qualification)
        .exclude(pk__in=excluded)
        .exclude(pk__in=on_leave)
    )


def eligible_reviewers(*, group, submitter, submission=None):
    """Users who may take a review task for this group's proposal right now.

    Pass ``submission`` to exclude the round's existing reviewers (a swap) and
    its 初审人 (nobody reviews what they themselves passed on).
    """
    return _eligible_pool(
        group=group,
        submitter=submitter,
        submission=submission,
        qualification=REVIEWER_QUALIFICATION,
    )


def eligible_preliminary_reviewers(*, group, submitter, submission=None):
    """Users who may take the 初审 task for this group's proposal right now."""
    return _eligible_pool(
        group=group,
        submitter=submitter,
        submission=submission,
        qualification=PRELIMINARY_QUALIFICATION,
    )


def _ensure_pool(*, candidates, count, label, qualification, hint):
    """Return the candidate list, refusing when it cannot fill ``count`` seats.

    Two callers need the same judgment — the draw, and the capacity check that
    keeps a round from opening when its review stage could never start — so the
    wording of the refusal lives here once.

    Leave is honoured by the caller's queryset, at draw time, rather than by
    flipping a qualification flag: the qualification never changes, so nothing
    has to be restored when a leave window ends. Only the *note* about leave is
    computed here, and it counts accounts that actually hold the qualification —
    a reviewer on leave is no reason a 初审 cannot be drawn, and vice versa.
    """
    candidates = list(candidates)
    if len(candidates) >= count:
        return candidates
    # Only reached on the failure path, so the extra queries are cheap here.
    on_leave = User.objects.filter(
        is_active=True,
        pk__in=ReviewerLeave.objects.active().values_list("reviewer_id", flat=True),
        **qualification,
    ).count()
    leave_note = f"（另有 {on_leave} 人请假）" if on_leave else ""
    shortfall = f"没有可用的{label}" if count == 1 else f"可用的{label}不足 {count} 人"
    raise ReviewError(f"当前{shortfall}{leave_note}，{hint}")


def _draw(*, candidates, count, label, qualification, hint):
    """Randomly draw ``count`` accounts, or refuse with the shortage message."""
    return random.sample(
        _ensure_pool(
            candidates=candidates,
            count=count,
            label=label,
            qualification=qualification,
            hint=hint,
        ),
        count,
    )


def _pick_preliminary_reviewer(*, group, submitter):
    """Draw the single 初审人 for a brand-new round."""
    drawn = _draw(
        candidates=eligible_preliminary_reviewers(group=group, submitter=submitter),
        count=1,
        label="初审人",
        qualification=PRELIMINARY_QUALIFICATION,
        hint="无法提交审核。",
    )
    return drawn[0]


def _pick_reviewers(*, group, submitter, count, submission=None, hint="无法提交审核。"):
    """Randomly draw the round's ordinary reviewers."""
    return _draw(
        candidates=eligible_reviewers(
            group=group, submitter=submitter, submission=submission
        ),
        count=count,
        label="评审人",
        qualification=REVIEWER_QUALIFICATION,
        hint=hint,
    )


def submit_for_review(*, group, submitter, review_type, message="", request=None):
    """Open a new review round and hand it to one 初审人.

    The round starts in 初审中 with no reviewers: the type's quota is spent by
    :func:`complete_preliminary_review`, so a proposal that is not ready never
    occupies the panel.

    The reviewers themselves are *not* reserved here, but the round is only
    opened if the pool could fill the quota right now. Otherwise a club that has
    not granted 评审资格 to enough accounts yet would open a round nobody can
    advance: the group cannot submit again (single-open-round rule) and the
    初审人 cannot pass it, leaving administrator intervention or a super
    reviewer's override as the only way out.
    """
    if review_type not in REVIEWER_QUOTA:
        raise ReviewError("请选择评审类型。")
    if not group.proposal:
        raise ReviewError("请先上传项目书，再提交审核。")

    with transaction.atomic():
        # Lock the group: without it, two submissions for the same group could
        # both pass the open-round check below and both compute the same next
        # round number, colliding on the (group, round) constraint.
        ProjectGroup.objects.select_for_update().get(pk=group.pk)
        open_round = (
            group.submissions.filter(status__in=ProjectSubmission.OPEN_STATUSES)
            .order_by("round")
            .first()
        )
        if open_round is not None:
            raise ReviewError(
                f"第 {open_round.round} 轮评审尚未结束，"
                "请等本轮出结论后再提交下一轮。"
            )

        preliminary_reviewer = _pick_preliminary_reviewer(
            group=group, submitter=submitter
        )
        # Capacity check only — nothing is drawn yet. The round's own 初审人 is
        # excluded because the later draw excludes them too: a 初审人 who is
        # also a reviewer does not get to fill one of the round's seats.
        _ensure_pool(
            candidates=eligible_reviewers(group=group, submitter=submitter).exclude(
                pk=preliminary_reviewer.pk
            ),
            count=REVIEWER_QUOTA[review_type],
            label="评审人",
            qualification=REVIEWER_QUALIFICATION,
            hint="无法提交审核。",
        )
        last = group.submissions.order_by("-round").first()
        round_number = (last.round + 1) if last else 1
        submission = ProjectSubmission.objects.create(
            group=group,
            round=round_number,
            review_type=review_type,
            message=message,
            submitted_by=submitter,
        )
        PreliminaryReview.objects.create(
            submission=submission,
            reviewer=preliminary_reviewer,
        )

    record_audit(
        action="reviews.submission.create",
        user=submitter,
        target=submission,
        detail={
            "group_id": group.pk,
            "round": round_number,
            "review_type": review_type,
            "preliminary_reviewer_id": preliminary_reviewer.pk,
        },
        request=request,
    )
    logger.info(
        "reviews.submission.create group_id=%s submission_id=%s round=%s review_type=%s preliminary_reviewer=%s submitter=%s",
        group.pk,
        submission.pk,
        round_number,
        review_type,
        preliminary_reviewer.pk,
        submitter.get_username(),
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return submission


def complete_preliminary_review(*, preliminary, reviewer, decision, comment, request=None):
    """Record the round's 初审 verdict; a 通过 then draws the reviewers.

    The draw happens here, inside the verdict's transaction, because 通过 is
    exactly the event that opens the full review. The pool was checked when the
    round was submitted, so a shortage here means it changed in between (a leave
    window started, a qualification was revoked): the whole call fails and the
    初审 task stays pending, so the 初审人 can submit again once reviewers are
    free — nothing is left half-decided, and the round does not sit in 评审中
    with nobody assigned to it.
    """
    if preliminary.reviewer_id != reviewer.pk:
        raise ReviewError("这不是分配给你的初审任务。")
    if decision not in dict(PreliminaryReview.DECISION_CHOICES):
        raise ReviewError("请选择初审决定。")

    with transaction.atomic():
        # Same lock order as complete_review (submission → task): the draw below
        # reads the round's state, so the parent row is what serialises it.
        submission = ProjectSubmission.objects.select_for_update().get(
            pk=preliminary.submission_id
        )
        locked = (
            PreliminaryReview.objects.select_for_update()
            .select_related("submission__group", "submission__submitted_by")
            .get(pk=preliminary.pk)
        )
        # Any non-pending state is final, for the same reason as in
        # complete_review: RELEASED means a super reviewer settled the round
        # first, and reviving it would rewrite a decided round.
        if locked.status != PreliminaryReview.PENDING:
            raise ReviewError("该初审任务已经处理过了，无法再次提交。")
        if submission.status != ProjectSubmission.PRELIMINARY_PENDING:
            raise ReviewError("该轮送审已不在初审环节。")

        now = timezone.now()
        locked.status = PreliminaryReview.COMPLETED
        locked.decision = decision
        locked.comment = comment
        locked.completed_at = now
        locked.save(
            update_fields=["status", "decision", "comment", "completed_at"]
        )

        reviewers = []
        if decision == PreliminaryReview.APPROVE:
            reviewers = _pick_reviewers(
                group=submission.group,
                submitter=submission.submitted_by,
                count=submission.required_reviewers,
                submission=submission,
                hint="无法通过初审，请稍后重试或联系管理员补充评审人。",
            )
            for reviewer_user in reviewers:
                ReviewAssignment.objects.create(
                    submission=submission, reviewer=reviewer_user
                )
            submission.status = ProjectSubmission.PENDING
            submission.save(update_fields=["status"])
        else:
            # 打回: the group revises the proposal and submits a new round,
            # exactly as when a reviewer asks for changes.
            submission.status = ProjectSubmission.NEEDS_REVISION
            submission.decided_at = now
            submission.save(update_fields=["status", "decided_at"])

    record_audit(
        action="reviews.preliminary.complete",
        user=reviewer,
        target=locked,
        detail={
            "submission_id": locked.submission_id,
            "decision": decision,
            "submission_status": submission.status,
            "reviewer_ids": [user.pk for user in reviewers],
        },
        request=request,
    )
    logger.info(
        "reviews.preliminary.complete preliminary_id=%s submission_id=%s decision=%s submission_status=%s reviewers=%s reviewer=%s",
        locked.pk,
        locked.submission_id,
        decision,
        submission.status,
        [user.pk for user in reviewers],
        reviewer.get_username(),
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return locked


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
        # Any non-pending state is final: COMPLETED means this reviewer has
        # already voted, RELEASED means a super reviewer settled the round
        # first. Without this guard a released task could be revived into the
        # record after the round was decided.
        if locked.status != ReviewAssignment.PENDING:
            raise ReviewError("该评审任务已经处理过了，无法再次提交。")

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


def override_blocker(*, submission, user):
    """Why this user may not decide this round outright; None when they may.

    The single definition of the rule, so the queue can explain itself, the
    change page can decide whether to offer the form, and the service can refuse
    with the same reason — none of them re-implement it. The conflict-of-interest
    rules match an ordinary reviewer's, and a super reviewer who already holds a
    task on this round must use that task instead — a 初审 task counts, since a
    round's first gate is still a seat on that round.

    A round in 初审中 is in progress like any other, so the override reaches it:
    that is how a round whose 初审人 went quiet is settled without waiting.
    """
    if not is_super_reviewer(user):
        return "没有超级评审资格"
    if submission is None or not submission.is_open:
        return "本轮已经出过结论"
    if user.pk == submission.submitted_by_id:
        return "你是本轮的提交人"
    if submission.group.members.filter(pk=user.pk).exists():
        return "你是本项目组成员"
    preliminary = preliminary_review_of(submission)
    if preliminary is not None and preliminary.reviewer_id == user.pk:
        if preliminary.status == PreliminaryReview.PENDING:
            return "你在本轮有初审任务，请直接提交那一条"
        return "你是本轮的初审人，已经就该轮给出初审意见"
    if submission.assignments.filter(reviewer=user).exists():
        return "你在本轮已有评审任务，请直接提交那一条"
    return None


def can_override_review(*, submission, user):
    """Whether this user may decide this round outright with a single vote."""
    return override_blocker(submission=submission, user=user) is None


def override_review(
    *,
    submission,
    super_reviewer,
    decision,
    comment,
    annotated_file=None,
    request=None,
):
    """Settle a round outright with a super reviewer's single vote.

    This deliberately does **not** go through :func:`_settle_submission`. That
    aggregation answers "did every reviewer approve?", so an earlier 需修改 from
    an ordinary reviewer would overrule the super reviewer — which is precisely
    the decision this path exists to make. The verdict is written directly and
    the reviewers still waiting are released.
    """
    if decision not in dict(ReviewAssignment.DECISION_CHOICES):
        raise ReviewError("请选择评审决定。")

    with transaction.atomic():
        locked = ProjectSubmission.objects.select_for_update().get(pk=submission.pk)
        blocker = override_blocker(submission=locked, user=super_reviewer)
        if blocker:
            raise ReviewError(f"无法行使超级评审权：{blocker}。")

        now = timezone.now()
        ReviewAssignment.objects.create(
            submission=locked,
            reviewer=super_reviewer,
            status=ReviewAssignment.COMPLETED,
            decision=decision,
            comment=comment,
            annotated_file=annotated_file or "",
            completed_at=now,
            is_override=True,
        )
        # Whoever was still being waited on is let go: the round no longer needs
        # them. Completed rows stay as they are — their verdict is history. A
        # round settled during 初审 has no reviewers yet, only that one task.
        released = locked.assignments.filter(status=ReviewAssignment.PENDING).update(
            status=ReviewAssignment.RELEASED
        )
        preliminary = preliminary_review_of(locked)
        released_preliminary = 0
        if preliminary is not None and preliminary.status == PreliminaryReview.PENDING:
            released_preliminary = PreliminaryReview.objects.filter(
                pk=preliminary.pk
            ).update(status=PreliminaryReview.RELEASED)

        locked.status = (
            ProjectSubmission.APPROVED
            if decision == ReviewAssignment.APPROVE
            else ProjectSubmission.NEEDS_REVISION
        )
        locked.decided_at = now
        locked.save(update_fields=["status", "decided_at"])

        if locked.status == ProjectSubmission.APPROVED:
            _archive_annotated_proposals(locked)

    record_audit(
        action="reviews.submission.override",
        user=super_reviewer,
        target=locked,
        detail={
            "submission_id": locked.pk,
            "decision": decision,
            "released": released,
            "released_preliminary": released_preliminary,
        },
        request=request,
    )
    logger.info(
        "reviews.submission.override submission_id=%s decision=%s released=%s released_preliminary=%s actor=%s",
        locked.pk,
        decision,
        released,
        released_preliminary,
        super_reviewer.get_username(),
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
            group=submission.group,
            submitter=submission.submitted_by,
            submission=submission,
        ).filter(pk=new_reviewer.pk).exists():
            raise ReviewError(
                "该账号当前不能评审本轮的送审"
                "（可能没有资格、正在请假，或是本轮的初审人）。"
            )

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


def reassign_preliminary_reviewer(*, preliminary, new_reviewer, actor, request=None):
    """Hand one pending 初审 task to a different 初审人.

    The same recovery path as :func:`reassign_reviewer`, and needed even more:
    the 初审 is the only way into a round, so a 初审人 who goes quiet would hold
    up the whole group, not just their own task. Only a pending task on a round
    still in 初审中 may be swapped — once the round moves on, the row records who
    passed it. The holder is mutated rather than replaced, so the round keeps
    exactly one 初审 task.
    """
    with transaction.atomic():
        # Same lock order as the rest of the app (submission → task).
        submission = ProjectSubmission.objects.select_for_update().get(
            pk=preliminary.submission_id
        )
        locked = (
            PreliminaryReview.objects.select_for_update()
            .select_related("submission__group", "submission__submitted_by")
            .get(pk=preliminary.pk)
        )
        if locked.status != PreliminaryReview.PENDING:
            raise ReviewError("只有待初审的任务可以更换初审人。")
        if submission.status != ProjectSubmission.PRELIMINARY_PENDING:
            raise ReviewError("该轮送审已不在初审环节，不能再更换初审人。")
        if locked.reviewer_id == new_reviewer.pk:
            raise ReviewError("初审人没有变化。")
        # The admin form limits the choices already; these checks are what make
        # the rule hold for any other caller too.
        if new_reviewer.pk == submission.submitted_by_id:
            raise ReviewError("提交人不能初审自己的项目书。")
        if submission.group.members.filter(pk=new_reviewer.pk).exists():
            raise ReviewError("该项目组成员不能初审本组的项目书。")
        if not eligible_preliminary_reviewers(
            group=submission.group,
            submitter=submission.submitted_by,
            submission=submission,
        ).filter(pk=new_reviewer.pk).exists():
            raise ReviewError("该账号当前不具备初审资格（可能已停用或正在请假）。")

        previous_reviewer_id = locked.reviewer_id
        locked.reviewer = new_reviewer
        locked.save(update_fields=["reviewer"])

    record_audit(
        action="reviews.preliminary.reassign",
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
        "reviews.preliminary.reassign preliminary_id=%s submission_id=%s from_reviewer_id=%s to_reviewer_id=%s actor=%s",
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


def count_pending_preliminary_reviews(reviewer):
    """How many 初审 tasks await this reviewer.

    Counted separately from :func:`count_pending_reviews` because the two are
    worded differently wherever they are shown ("待初审" vs "待评审"); a
    reviewer holding both kinds gets one reminder naming both.
    """
    return PreliminaryReview.objects.filter(
        reviewer=reviewer,
        status=PreliminaryReview.PENDING,
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
    if not (reviewer.is_reviewer or reviewer.is_preliminary_reviewer):
        raise ReviewError("该账号没有评审或初审资格，无需请假。")
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
