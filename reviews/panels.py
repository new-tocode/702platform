"""页面上下文的单一入口：队列页、项目组详情页、成员中心。

装配逻辑过去散在三个 app 里（projects 的 ``group_detail``、accounts 的
``member_home`` 与登录提醒），于是「评审面板长什么样」要在别的应用里找。这里只做
「挑出我这一份、配好表单」——判断在 :mod:`reviews.permissions` 与
:mod:`reviews.services`，取数留给调用方（页面还要用同一批对象渲染别的区块）。

调用方一律局部 import 本模块，免得 projects／accounts 在加载期就依赖 reviews。
"""

from django.utils import timezone

from projects.models import GroupCreateRequest
from projects.permissions import can_decide_group_create_requests

from . import permissions
from .forms import PreliminaryReviewForm, ReviewForm, ReviewerLeaveForm
from .models import (
    ReviewTask,
    ProjectSubmission,
    preliminary_task_of,
)
from .services import (
    can_override_review,
    open_leave_for,
    override_blocker,
    pending_task_summary,
)


def queue_context(*, user):
    """「我的评审」页：按资格决定显示哪几侧，并把任务按（阶段，状态）分档。

    分档在 Python 里做而不是六次 DB 查询：一名评审人手上的任务是个位数量级，
    一次取回再分，比按状态各查一次更省也更好读。
    """
    context = {
        "show_preliminary": permissions.is_preliminary_reviewer(user),
        # 超级评审没有自己的队列任务，但整页都归他们看，所以也算「评审」这一侧。
        "show_review": permissions.is_reviewer(user)
        or permissions.is_super_reviewer(user),
    }
    tasks = list(
        ReviewTask.objects.filter(reviewer=user)
        .select_related("submission__group", "submission__submitted_by")
        .order_by("-assigned_at", "-id")
    )

    def bucket(stage, status):
        return [task for task in tasks if task.stage == stage and task.status == status]

    if context["show_preliminary"]:
        context["preliminary_pending"] = bucket(
            ReviewTask.PRELIMINARY, ReviewTask.PENDING
        )
        context["preliminary_completed"] = bucket(
            ReviewTask.PRELIMINARY, ReviewTask.COMPLETED
        )
        # 被超级评审释放的那一条也要列出来：否则初审人只会看到任务凭空消失。
        context["preliminary_released"] = bucket(
            ReviewTask.PRELIMINARY, ReviewTask.RELEASED
        )
    if context["show_review"]:
        context["pending"] = bucket(ReviewTask.REVIEW, ReviewTask.PENDING)
        context["completed"] = bucket(ReviewTask.REVIEW, ReviewTask.COMPLETED)
        context["released"] = bucket(ReviewTask.REVIEW, ReviewTask.RELEASED)
    if permissions.is_super_reviewer(user):
        context["open_rounds"] = open_rounds_for(user)
    if can_decide_group_create_requests(user):
        context["create_requests"] = pending_create_requests()
    return context


def pending_create_requests():
    """全体管理员的共同待办：还没有人处理的创建项目组申请。

    任一位管理员处理后这条就不再是 pending，其他人的队列里随之消失。
    """
    return list(
        GroupCreateRequest.objects.filter(status=GroupCreateRequest.PENDING)
        .select_related("applicant__profile")
        .order_by("created_at", "id")
    )


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
    键名与合并前一致（``my_preliminary``／``my_assignment``／两个表单），所以模板与
    既有断言都不用动——两条 URL 也仍然指向同一个视图。
    """
    latest = submissions[0] if submissions else None
    my_task = _pending_task_of(latest, user)
    can_override = latest is not None and can_override_review(
        submission=latest,
        user=user,
    )
    context = {
        "my_preliminary": my_task if my_task and my_task.is_preliminary else None,
        "my_assignment": my_task if my_task and my_task.is_review else None,
        "review_form": ReviewForm(),
        "preliminary_form": PreliminaryReviewForm(),
        "can_override": can_override,
    }
    if can_override:
        # Prefixed so its field ids cannot clash with the reviewer form above.
        context["override_form"] = ReviewForm(prefix="override")
    return context


def _pending_task_of(submission, user):
    """我和这一轮之间那条还没交的任务。

    一个人在一轮里只有一席（``unique_submission_reviewer``），所以至多一条；资格
    也一并检查——任务还挂着但资格已被撤销的人，不该看到一个自己也提交不了的表单。
    """
    if submission is None or not user.is_authenticated:
        return None
    return next(
        (
            task
            for task in submission.tasks.all()
            if task.reviewer_id == user.pk
            and task.is_pending
            and permissions.qualifies_for_stage(user, task.stage)
        ),
        None,
    )


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
