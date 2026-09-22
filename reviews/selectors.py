"""评审的读与策略：手上还有多少活、请假窗口、超级评审能不能行使。

只读不写，与 :mod:`reviews.services` 的写命令分开——页面装配（``panels``）、
登录提醒和后台都要问「现在是什么情况」，它们不需要也不该碰事务。
"""

from typing import NamedTuple

from django.db.models import Count
from django.utils.translation import gettext_lazy as _, ngettext

from . import lifecycle
from .models import (
    ReviewTask,
    ReviewerLeave,
    preliminary_task_of,
)
from .permissions import is_super_reviewer


class PendingTasks(NamedTuple):
    """待办的唯一口径：两种数量，以及两处页面各自要的措辞。

    措辞写在这里而不是各处页面上：登录提醒、成员中心的待办卡片与队列页统计条
    用的是同一批数字，三处各拼一句就会慢慢长歪。
    """

    preliminary: int
    review: int

    @property
    def total(self):
        return self.preliminary + self.review

    @property
    def parts(self):
        """登录提醒用：``["2 份项目书待初审", "1 份项目书待评审"]``。"""
        parts = []
        # 中文单复数同形，所以单数那一半直接写死 1（数量在句首，中文读起来一样）；
        # 英文才分得清 1 proposal / 2 proposals。
        if self.preliminary:
            parts.append(
                ngettext("1 份项目书待初审", "%(count)s 份项目书待初审", self.preliminary)
                % {"count": self.preliminary}
            )
        if self.review:
            parts.append(
                ngettext("1 份项目书待评审", "%(count)s 份项目书待评审", self.review)
                % {"count": self.review}
            )
        return parts

    @property
    def headline(self):
        """成员中心卡片用；数字由模板单独渲染，这里只给后面那半句。"""
        if self.preliminary and self.review:
            return _("份项目书待你处理（初审 %(preliminary)s · 评审 %(review)s）") % {
                "preliminary": self.preliminary,
                "review": self.review,
            }
        if self.preliminary:
            # 数字由模板单独渲染（<span class="n">），句子这边不带数量，英文因此
            # 没法按单复数变形——译文才用不带名词的写法，中文一字未动。
            return _("份项目书待你初审")
        if self.review:
            return _("份项目书待你评审")
        return ""


def pending_task_summary(reviewer):
    """这个账号手上还没交的任务，按阶段计数——一次查询。

    The single place that answers "how much is waiting for me": the post-login
    nudge, the member-centre card and the queue page all come through here.
    Leave is deliberately not applied — taking leave does not excuse the tasks a
    reviewer already holds.
    """
    rows = dict(
        ReviewTask.objects.filter(reviewer=reviewer, status=ReviewTask.PENDING)
        .values_list("stage")
        .annotate(count=Count("pk"))
    )
    return PendingTasks(
        preliminary=rows.get(ReviewTask.PRELIMINARY, 0),
        review=rows.get(ReviewTask.REVIEW, 0),
    )


def open_leave_for(reviewer, at=None):
    """The reviewer's not-yet-ended leave, if they have one."""
    return (
        ReviewerLeave.objects.filter(reviewer=reviewer)
        .open(at)
        .order_by("-starts_at", "-id")
        .first()
    )


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
        return _("没有超级评审资格")
    if submission is None or not submission.is_open:
        return _("本轮已经出过结论")
    if user.pk == submission.submitted_by_id:
        return _("你是本轮的提交人")
    if submission.group.members.filter(pk=user.pk).exists():
        return _("你是本项目组成员")
    preliminary = preliminary_task_of(submission)
    if preliminary is not None and preliminary.reviewer_id == user.pk:
        if preliminary.status == ReviewTask.PENDING:
            label = lifecycle.STAGES[lifecycle.STAGE_PRELIMINARY].label
            return _("你在本轮已有%(stage)s任务，请直接提交那一条") % {"stage": label}
        return _("你是本轮的初审人，已经就该轮给出初审意见")
    if submission.tasks.filter(reviewer=user).exists():
        return _("你在本轮已有评审任务，请直接提交那一条")
    return None


def can_override_review(*, submission, user):
    """Whether this user may decide this round outright with a single vote."""
    return override_blocker(submission=submission, user=user) is None
