"""页面上下文的单一入口：队列页、项目组详情页、成员中心。

装配逻辑过去散在三个 app 里（projects 的 ``group_detail``、accounts 的
``member_home`` 与登录提醒），于是「评审面板长什么样」要在别的应用里找。这里只做
「挑出我这一份、配好表单」——判断在 :mod:`reviews.permissions` 与
:mod:`reviews.services`，取数留给调用方（页面还要用同一批对象渲染别的区块）。

调用方一律局部 import 本模块，免得 projects／accounts 在加载期就依赖 reviews。
"""

from django.utils import timezone

from . import permissions
from .forms import PreliminaryReviewForm, ReviewForm, ReviewerLeaveForm
from .models import (
    PreliminaryReview,
    ProjectSubmission,
    ReviewAssignment,
    preliminary_review_of,
)
from .services import (
    can_override_review,
    open_leave_for,
    override_blocker,
    pending_task_summary,
)


def queue_context(*, user):
    """「我的评审」页：按资格决定显示哪几侧，并把任务分档。

    分档在 Python 里做而不是三次 DB 查询：一名评审人手上的任务是个位数量级，
    一次取回再分，比按状态各查一次更省也更好读。
    """
    context = {
        "show_preliminary": permissions.is_preliminary_reviewer(user),
        # 超级评审没有自己的队列任务，但整页都归他们看，所以也算「评审」这一侧。
        "show_review": permissions.is_reviewer(user)
        or permissions.is_super_reviewer(user),
    }
    if context["show_preliminary"]:
        preliminary = (
            PreliminaryReview.objects.filter(reviewer=user)
            .select_related("submission__group", "submission__submitted_by")
            .order_by("-assigned_at", "-id")
        )
        context["preliminary_pending"] = [
            item for item in preliminary if item.status == PreliminaryReview.PENDING
        ]
        context["preliminary_completed"] = [
            item for item in preliminary if item.status == PreliminaryReview.COMPLETED
        ]
        # 被超级评审释放的那一条也要列出来：否则初审人只会看到任务凭空消失。
        context["preliminary_released"] = [
            item for item in preliminary if item.status == PreliminaryReview.RELEASED
        ]
    if context["show_review"]:
        assignments = (
            ReviewAssignment.objects.filter(reviewer=user)
            .select_related("submission__group", "submission__submitted_by")
            .order_by("-assigned_at", "-id")
        )
        context["pending"] = [
            item for item in assignments if item.status == ReviewAssignment.PENDING
        ]
        context["completed"] = [
            item for item in assignments if item.status == ReviewAssignment.COMPLETED
        ]
        context["released"] = [
            item for item in assignments if item.status == ReviewAssignment.RELEASED
        ]
    if permissions.is_super_reviewer(user):
        context["open_rounds"] = open_rounds_for(user)
    return context


def open_rounds_for(user):
    """超级评审的「全部进行中」：每一轮连同「这个人能不能行使」的原因。

    Rounds they cannot act on stay listed — seeing the whole picture is the point
    — but each says why.
    """
    return [
        {
            "submission": submission,
            "blocker": override_blocker(submission=submission, user=user),
        }
        for submission in ProjectSubmission.objects.filter(
            status__in=ProjectSubmission.OPEN_STATUSES
        )
        .select_related("group", "submitted_by")
        .order_by("submitted_at", "id")
    ]


def group_detail_context(*, submissions, user):
    """项目组详情页里评审那一半。

    ``submissions`` 是该组的轮次（新到旧）且已预取任务与提交人；本函数不补查询。
    """
    latest = submissions[0] if submissions else None
    my_assignment = None
    my_preliminary = None
    if latest is not None:
        if permissions.is_reviewer(user):
            my_assignment = next(
                (
                    assignment
                    for assignment in latest.assignments.all()
                    if assignment.reviewer_id == user.pk
                    and assignment.status == ReviewAssignment.PENDING
                ),
                None,
            )
        if permissions.is_preliminary_reviewer(user):
            preliminary = preliminary_review_of(latest)
            if (
                preliminary is not None
                and preliminary.reviewer_id == user.pk
                and preliminary.status == PreliminaryReview.PENDING
            ):
                my_preliminary = preliminary
    can_override = latest is not None and can_override_review(
        submission=latest,
        user=user,
    )
    context = {
        "my_assignment": my_assignment,
        "my_preliminary": my_preliminary,
        "review_form": ReviewForm(),
        "preliminary_form": PreliminaryReviewForm(),
        "can_override": can_override,
    }
    if can_override:
        # Prefixed so its field ids cannot clash with the reviewer form above.
        context["override_form"] = ReviewForm(prefix="override")
    return context


def member_home_context(*, user):
    """成员中心里评审那一半；没有评审资格的账号得到空字典（模板整块不渲染）。"""
    if not permissions.has_review_qualification(user):
        return {}
    context = {"pending": pending_task_summary(user)}
    if permissions.may_receive_tasks(user):
        leave = open_leave_for(user)
        context["reviewer_leave"] = leave
        context["leave_form"] = ReviewerLeaveForm(initial=_leave_initial(leave))
    return context


def _leave_initial(leave):
    """请假表单的初值：有未结束的窗口就照抄，没有就默认从此刻开始。"""
    if leave is None:
        return {"starts_at": timezone.localtime(timezone.now())}
    return {
        "starts_at": leave.starts_at,
        "ends_at": leave.ends_at,
        "reason": leave.reason,
    }
