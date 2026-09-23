"""Transactional project-proposal review operations.

Reviewer assignment, verdict aggregation and archiving live here so the rules
"a round needs as many reviewers as its type demands" and "every reviewer must
approve" each have exactly one implementation.

A round has two stages, and both are :class:`~reviews.models.ReviewTask` rows
distinguished by ``stage``: one 初审人 gets the proposal first, and only their
通过 draws the ordinary reviewers (:func:`_open_review_stage`). Everything that
is not stage-specific — who may hold a task, what a task may do next, how a
verdict is recorded — is therefore written once (:func:`submit_verdict`) and
parameterised by :data:`reviews.lifecycle.STAGES`.

本模块只放写命令（改状态、写任务、留审计）。抽签在 :mod:`reviews.draw`，
只读的计数与策略在 :mod:`reviews.selectors`——它们过去都挤在这里，819 行里
真正写库的不到一半。
"""

import logging
import os

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.audit import record_audit
from projects.models import ProjectGroup

from . import lifecycle

# 抽签与只读查询已分别搬到 draw / selectors，但各调用方（views、panels、
# forms、admin、accounts.signals 以及各测试模块）一直从本模块取这些名字，
# 所以照旧转出，import 路径不变。
from .draw import draw_tasks, eligible_holders, ensure_pool, qualification_for
from .exceptions import ReviewError
from .permissions import may_receive_tasks
from .selectors import (
    PendingTasks,
    can_override_review,
    open_leave_for,
    override_blocker,
    pending_task_summary,
)

from .models import (
    REVIEWER_QUOTA,
    ArchivedProposal,
    ReviewTask,
    ProjectSubmission,
    ReviewerLeave,
)


logger = logging.getLogger(__name__)


def _advance(submission, event, *, at=None):
    """把这一轮推到事件的落点；不允许时用事件自带的那句话拒绝。

    状态怎么走由 :mod:`reviews.lifecycle` 的迁移表说了算，这里只负责把「给用户
    看的话」翻译成 :class:`ReviewError`——lifecycle 不认识这个异常，两边互不 import。
    """
    reason = lifecycle.transition_refusal(submission, event)
    if reason:
        raise ReviewError(reason)
    return lifecycle.transition(submission, event, at=at)


def submit_for_review(*, group, submitter, review_type, message="", request=None):
    """Open a new review round and hand it to one 初审人.

    The round starts in 初审中 with no reviewers: the type's quota is spent by
    :func:`_open_review_stage` once the 初审 passes, so a proposal that is not
    ready never occupies the panel.

    The reviewers themselves are *not* reserved here, but the round is only
    opened if the pool could fill the quota right now. Otherwise a club that has
    not granted 评审资格 to enough accounts yet would open a round nobody can
    advance: the group cannot submit again (single-open-round rule) and the
    初审人 cannot pass it, leaving administrator intervention or a super
    reviewer's override as the only way out.
    """
    if review_type not in REVIEWER_QUOTA:
        raise ReviewError(_("请选择评审类型。"))
    if not group.proposal:
        raise ReviewError(_("请先上传项目书，再提交审核。"))

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
                _("第 %(round)s 轮评审尚未结束，请等本轮出结论后再提交下一轮。")
                % {"round": open_round.round}
            )

        preliminary_reviewer = draw_tasks(
            stage=lifecycle.STAGE_PRELIMINARY,
            group=group,
            submitter=submitter,
            count=1,
        )[0]
        # Capacity check only — nothing is drawn yet. The round's own 初审人 is
        # excluded because the later draw excludes them too: a 初审人 who is
        # also a reviewer does not get to fill one of the round's seats.
        ensure_pool(
            candidates=eligible_holders(
                stage=lifecycle.STAGE_REVIEW, group=group, submitter=submitter
            ).exclude(pk=preliminary_reviewer.pk),
            count=REVIEWER_QUOTA[review_type],
            label=lifecycle.STAGES[lifecycle.STAGE_REVIEW].holder_label,
            qualification=qualification_for(lifecycle.STAGE_REVIEW),
            hint=_("无法提交审核。"),
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
        ReviewTask.objects.create(
            submission=submission,
            stage=ReviewTask.PRELIMINARY,
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


def _archive_annotated_proposals(submission):
    """Copy every annotated proposal of an approved round into the archive.

    Reviewers who answered with text only leave no row: an archive entry
    without a file would carry no information. ``get_or_create`` plus the
    uniqueness on ``source_task`` keeps a retried aggregation idempotent.
    """
    annotated = submission.tasks.filter(
        status=ReviewTask.COMPLETED,
        decision=ReviewTask.APPROVE,
    ).exclude(annotated_file="")
    archived_count = 0
    for assignment in annotated:
        archived, created = ArchivedProposal.objects.get_or_create(
            source_task=assignment,
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
    which also makes the archiving below idempotent — the guard that keeps a vote
    from being recorded on a decided round lives in :func:`complete_review`, so
    reaching here with anything but 评审中 means "nothing left to aggregate".
    """
    if submission.status != ProjectSubmission.PENDING:
        return submission
    if submission.tasks.filter(status=ReviewTask.PENDING).exists():
        return submission

    has_revision_request = submission.tasks.filter(
        decision=ReviewTask.REVISE
    ).exists()
    lifecycle.transition(
        submission,
        lifecycle.REVIEWS_REVISED if has_revision_request else lifecycle.REVIEWS_APPROVED,
    )

    if submission.status == ProjectSubmission.APPROVED:
        _archive_annotated_proposals(submission)
    return submission


def submit_verdict(
    *,
    task,
    reviewer,
    decision,
    comment,
    annotated_file=None,
    request=None,
):
    """交一张任务卡：写下结论，并让这一轮该发生的后续发生。

    两道关共用这一条路径——「是不是分配给你的、结论合不合法、这张卡还能不能交、
    轮次还停不停止在这一关」这些校验、加锁顺序（submission → task）、审计与日志
    的形状全都相同，差别只在交完之后：

    * 初审**通过** → 当场按送审类型抽齐评审人，轮次转入评审（:func:`_open_review_stage`）；
    * 初审**打回** → 本轮结束，项目组改稿后再送新一轮；
    * 评审**交卷** → 尝试汇总本轮（:func:`_settle_submission`），全员通过才算通过。

    批注版项目书只有评审阶段接收：初审给的是理由，不是稿子（表单也不给这个字段）。
    """
    stage = task.stage
    rules = lifecycle.STAGES[stage]
    if task.reviewer_id != reviewer.pk:
        raise ReviewError(_("这不是分配给你的%(stage)s任务。") % {"stage": rules.label})
    if decision not in dict(ReviewTask.DECISION_CHOICES):
        raise ReviewError(_("请选择%(stage)s决定。") % {"stage": rules.label})

    with transaction.atomic():
        # Lock the parent row first. The aggregation in _settle_submission reads
        # the round's other tasks, so locking only this one would let two people
        # finishing at the same time each see the other as still pending — and
        # leave the round stuck at 评审中 forever. Lock order is always
        # submission → task.
        submission = ProjectSubmission.objects.select_for_update().get(
            pk=task.submission_id
        )
        locked = (
            ReviewTask.objects.select_for_update()
            .select_related("submission__group", "submission__submitted_by")
            .get(pk=task.pk)
        )
        # Any non-pending state is final: COMPLETED means this holder has already
        # answered, RELEASED means a super reviewer settled the round first.
        # Without this guard a released task could be revived into the record
        # after the round was decided.
        if locked.status != ReviewTask.PENDING:
            raise ReviewError(
                _("该%(stage)s任务已经处理过了，无法再次提交。") % {"stage": rules.label}
            )
        # 轮次必须还停在这道关上，否则这一票会写进一条已经走过的轮次。
        reason = lifecycle.open_stage_refusal(submission, stage)
        if reason:
            raise ReviewError(reason)

        now = timezone.now()
        locked.status = ReviewTask.COMPLETED
        locked.decision = decision
        locked.comment = comment
        locked.completed_at = now
        update_fields = ["status", "decision", "comment", "completed_at"]
        if stage == ReviewTask.REVIEW and annotated_file is not None:
            locked.annotated_file = annotated_file
            update_fields.append("annotated_file")
        locked.save(update_fields=update_fields)

        drawn = []
        if stage == ReviewTask.PRELIMINARY:
            if decision == ReviewTask.APPROVE:
                drawn = _open_review_stage(submission)
            else:
                _advance(submission, lifecycle.PRELIMINARY_REVISED, at=now)
        else:
            _settle_submission(submission)

    record_audit(
        action=rules.submit_action,
        user=reviewer,
        target=locked,
        detail={
            "submission_id": locked.submission_id,
            "stage": stage,
            "decision": decision,
            "submission_status": submission.status,
            "annotated": annotated_file is not None,
            # 初审通过时一并记下抽到的评审人（名单本身就是这一刻的结果）。
            "reviewer_ids": [user.pk for user in drawn],
        },
        request=request,
    )
    logger.info(
        "%s task_id=%s submission_id=%s stage=%s decision=%s submission_status=%s annotated=%s reviewer=%s",
        rules.submit_action,
        locked.pk,
        locked.submission_id,
        stage,
        decision,
        submission.status,
        annotated_file is not None,
        reviewer.get_username(),
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return locked


def _open_review_stage(submission):
    """初审通过：轮次转「评审中」，并按送审类型把评审人抽齐。

    先过闸再抽人，两者在同一事务里：池子不够就整次回滚——结论不落库、初审任务
    仍待处理，初审人可以在有人空闲后原地重试，轮次也不会停在「评审中」却无人可派。
    """
    _advance(submission, lifecycle.PRELIMINARY_APPROVED)
    reviewers = draw_tasks(
        stage=lifecycle.STAGE_REVIEW,
        group=submission.group,
        submitter=submission.submitted_by,
        count=submission.required_reviewers,
        submission=submission,
        hint=_("无法通过初审，请稍后重试或联系管理员补充评审人。"),
    )
    for reviewer_user in reviewers:
        ReviewTask.objects.create(
            submission=submission,
            stage=ReviewTask.REVIEW,
            reviewer=reviewer_user,
        )
    return reviewers


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
    if decision not in dict(ReviewTask.DECISION_CHOICES):
        raise ReviewError(_("请选择评审决定。"))

    with transaction.atomic():
        locked = ProjectSubmission.objects.select_for_update().get(pk=submission.pk)
        blocker = override_blocker(submission=locked, user=super_reviewer)
        if blocker:
            raise ReviewError(_("无法行使超级评审权：%(reason)s。") % {"reason": blocker})

        now = timezone.now()
        ReviewTask.objects.create(
            submission=locked,
            stage=ReviewTask.REVIEW,
            reviewer=super_reviewer,
            status=ReviewTask.COMPLETED,
            decision=decision,
            comment=comment,
            annotated_file=annotated_file or "",
            completed_at=now,
            is_override=True,
        )
        # 等待中的所有任务一起放掉——两道关都算，本轮不再需要它们。已完成的行
        # 原样保留：它们的结论是历史。（在初审中敲定时，等待的只有那一条初审。）
        released = locked.tasks.filter(status=ReviewTask.PENDING).update(
            status=ReviewTask.RELEASED
        )

        lifecycle.transition(
            locked,
            lifecycle.OVERRIDE_APPROVED
            if decision == ReviewTask.APPROVE
            else lifecycle.OVERRIDE_REVISED,
            at=now,
        )

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
        },
        request=request,
    )
    logger.info(
        "reviews.submission.override submission_id=%s decision=%s released=%s actor=%s",
        locked.pk,
        decision,
        released,
        super_reviewer.get_username(),
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return locked


def reassign_task(*, task, new_reviewer, actor, request=None):
    """把一张还没交的任务卡换个人——管理员侧的补救路径。

    两道关共用这一条：规则完全相同（原地换人、一轮一人一席、不重新判结论、不触碰
    归档），只有措辞按阶段从 :data:`lifecycle.STAGES` 取。这是评审人／初审人失联，
    或事后发现其与本项目组有利益冲突时**唯一**的补救路径——没有它，该轮会永久停在
    「评审中」或「初审中」。

    Only a pending task on a round that has not moved past its stage may be
    swapped. Once the round moves on, the row records who decided — swapping the
    holder would re-attribute that decision (and its comment and annotated file)
    to somebody who never made it.
    """
    rules = lifecycle.STAGES[task.stage]
    with transaction.atomic():
        # Same lock order as submit_verdict (submission → task): someone
        # answering concurrently would settle the round, after which reassigning
        # it would no longer be sound.
        submission = ProjectSubmission.objects.select_for_update().get(
            pk=task.submission_id
        )
        locked = (
            ReviewTask.objects.select_for_update()
            .select_related("submission__group", "submission__submitted_by")
            .get(pk=task.pk)
        )
        if locked.status != ReviewTask.PENDING:
            raise ReviewError(rules.swap_not_pending)
        if not lifecycle.stage_is_open(submission, locked.stage):
            raise ReviewError(rules.swap_phase)
        if locked.reviewer_id == new_reviewer.pk:
            raise ReviewError(_("%(role)s没有变化。") % {"role": rules.holder_label})
        # The admin form limits the choices already; these checks are what make
        # the rule hold for any other caller too.
        if new_reviewer.pk == submission.submitted_by_id:
            raise ReviewError(_("提交人不能%(stage)s自己的项目书。") % {"stage": rules.label})
        if submission.group.members.filter(pk=new_reviewer.pk).exists():
            raise ReviewError(_("该项目组成员不能%(stage)s本组的项目书。") % {"stage": rules.label})
        # 一人一轮一席：他要是已经持有本轮的（任何一条）任务，换过去就破了这条
        # 不变式——同一条检查对两道关都成立，文案取自 StageRules。
        if (
            submission.tasks.filter(reviewer=new_reviewer)
            .exclude(pk=locked.pk)
            .exists()
        ):
            raise ReviewError(rules.swap_holds)
        if not eligible_holders(
            stage=locked.stage,
            group=submission.group,
            submitter=submission.submitted_by,
            submission=submission,
        ).filter(pk=new_reviewer.pk).exists():
            raise ReviewError(
                _("该账号当前不能接手本轮的%(stage)s（可能没有资格、正在请假，或已在本轮持有任务）。")
                % {"stage": rules.label}
            )

        previous_reviewer_id = locked.reviewer_id
        locked.reviewer = new_reviewer
        locked.save(update_fields=["reviewer"])

    record_audit(
        action=rules.reassign_action,
        user=actor,
        target=locked,
        detail={
            "submission_id": locked.submission_id,
            "stage": locked.stage,
            "from_reviewer_id": previous_reviewer_id,
            "to_reviewer_id": new_reviewer.pk,
        },
        request=request,
    )
    logger.info(
        "%s task_id=%s submission_id=%s stage=%s from_reviewer_id=%s to_reviewer_id=%s actor=%s",
        rules.reassign_action,
        locked.pk,
        locked.submission_id,
        locked.stage,
        previous_reviewer_id,
        new_reviewer.pk,
        actor.get_username(),
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return locked


def set_reviewer_leave(*, reviewer, starts_at, ends_at, reason="", actor, request=None):
    """Register or adjust the reviewer's open leave window.

    A reviewer holds at most one open window, so registering again edits that
    one instead of stacking a second. This is also how a reviewer or an
    administrator moves the recovery time earlier or later.
    """
    if not may_receive_tasks(reviewer):
        raise ReviewError(_("该账号没有评审或初审资格，无需请假。"))
    if ends_at <= starts_at:
        raise ReviewError(_("请假结束时间必须晚于开始时间。"))
    if ends_at <= timezone.now():
        raise ReviewError(_("请假结束时间必须晚于当前时间。"))

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
        raise ReviewError(_("当前没有可取消的请假。"))

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
