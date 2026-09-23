"""抽签：谁可能被抽为初审人或评审人，以及抽不出来时怎么解释。

这里只查库、不写库，也不碰轮次状态——写命令在 :mod:`reviews.services`。
「谁可以审这份项目书」全平台只有一个实现（:func:`eligible_holders`），
抽人与管理员改派共用它，两边的排除条件因此不会各走各的。
"""

import random

from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from . import lifecycle
from .exceptions import ReviewError
from .models import ReviewerLeave


User = get_user_model()


def qualification_for(stage):
    """这道关的资格条件，从 :data:`lifecycle.STAGES` 翻译成查询参数。"""
    return {lifecycle.STAGES[stage].qualification: True}


def _eligible_pool(*, group, submitter, qualification, submission=None):
    """Accounts that may take a task of this kind on this group's proposal now.

    The single definition of "who may review", shared by every draw and by an
    administrator's manual reassignment, so the exclusions cannot drift apart
    between them:

    * the submitter and the group's members (conflict of interest),
    * anyone on leave (their window covers both kinds of task),
    * whoever already holds a task on this round — **两道关一起算**: a 初审人 who
      passed a round is not drawn as one of its reviewers, since letting one
      person both open and judge the same round hands their single opinion two
      slots in it. (合并成一张任务表之前，这里要额外查一次初审任务；现在
      ``submission.tasks`` 本身就含两道关，排除自然成立。)
    """
    excluded = set(group.members.values_list("pk", flat=True))
    excluded.add(submitter.pk)
    if submission is not None:
        excluded |= set(submission.tasks.values_list("reviewer_id", flat=True))
    on_leave = set(ReviewerLeave.objects.active().values_list("reviewer_id", flat=True))
    return (
        User.objects.filter(is_active=True, **qualification)
        .exclude(pk__in=excluded)
        .exclude(pk__in=on_leave)
    )


def eligible_holders(*, stage, group, submitter, submission=None):
    """谁可以接手这一道关的任务——抽人与管理员改派共用同一份名单。

    Pass ``submission`` to also exclude whoever already holds a task on the round
    (both stages count, so a 初审人 is never offered the review seats of the round
    they just let through).
    """
    return _eligible_pool(
        group=group,
        submitter=submitter,
        submission=submission,
        qualification=qualification_for(stage),
    )


def ensure_pool(*, candidates, count, label, qualification, hint):
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
    leave_note = _("（另有 %(count)s 人请假）") % {"count": on_leave} if on_leave else ""
    if count == 1:
        shortfall = _("没有可用的%(role)s") % {"role": label}
    else:
        shortfall = _("可用的%(role)s不足 %(count)s 人") % {"role": label, "count": count}
    raise ReviewError(
        _("当前%(shortfall)s%(leave)s，%(hint)s")
        % {"shortfall": shortfall, "leave": leave_note, "hint": hint}
    )


def _draw(*, candidates, count, label, qualification, hint):
    """Randomly draw ``count`` accounts, or refuse with the shortage message."""
    return random.sample(
        ensure_pool(
            candidates=candidates,
            count=count,
            label=label,
            qualification=qualification,
            hint=hint,
        ),
        count,
    )


def draw_tasks(*, stage, group, submitter, count, submission=None, hint=_("无法提交审核。")):
    """从这一道关的候选里随机抽 ``count`` 个人。"""
    return _draw(
        candidates=eligible_holders(
            stage=stage, group=group, submitter=submitter, submission=submission
        ),
        count=count,
        label=lifecycle.STAGES[stage].holder_label,
        qualification=qualification_for(stage),
        hint=hint,
    )
