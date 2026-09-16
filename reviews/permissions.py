"""评审资格，以及「凭评审身份能不能看这个项目组」的判定。

这些判断过去住在 ``projects/permissions.py`` 里，于是 projects 为了问一句「这个人
是不是评审人」要反过来 import 评审模型。判定归还给评审应用：

* projects 只保留项目组自己的口径（staff／成员／联系人）；
* 需要评审那一支时委托这里的 ``has_review_claim``（局部 import，保住「projects
  不在加载期依赖 reviews」这条既有约定）。

依赖方向因此是单向的：``reviews`` → ``projects`` 只有模型层的 ``ProjectGroup``
外键，``projects`` → ``reviews`` 只在函数体内、且只指向本模块。
"""

from . import lifecycle
from .models import ProjectSubmission, ReviewTask


def is_reviewer(user):
    """持有评审资格。"""
    return bool(
        user and user.is_authenticated and getattr(user, "is_reviewer", False)
    )


def is_preliminary_reviewer(user):
    """持有初审资格。"""
    return bool(
        user
        and user.is_authenticated
        and getattr(user, "is_preliminary_reviewer", False)
    )


def is_super_reviewer(user):
    """持有超级评审资格（一票敲定）。"""
    return bool(
        user and user.is_authenticated and getattr(user, "is_super_reviewer", False)
    )


def qualifies_for_stage(user, stage):
    """持有这一道关的资格。资格字段名由 :data:`lifecycle.STAGES` 给出。

    一个新阶段只要在阶段表里写好 ``qualification``，这里、抽人、改派与「谁看得见
    这一组」就全跟着生效。
    """
    if not (user and user.is_authenticated):
        return False
    return bool(getattr(user, lifecycle.STAGES[stage].qualification, False))


def has_review_qualification(user):
    """三种资格中的任意一种——「评审」入口与评审队列的门槛。

    超级评审也算：他们手上一份任务都没有时，整份工作是「看全部进行中的轮次」。
    """
    return any(
        qualifies_for_stage(user, stage) for stage in lifecycle.STAGES
    ) or is_super_reviewer(user)


def may_receive_tasks(user):
    """会收到任务的那两种资格——请假面板与请假服务的门槛。

    超级评审不接任务，也就没有「请假不收任务」这回事。
    """
    return any(qualifies_for_stage(user, stage) for stage in lifecycle.STAGES)


def has_review_claim(user, group):
    """凭评审身份对这一组的可见性主张（与项目组那一侧的口径取并集）。

    超级评审的视野是「进行中的轮次」——他们要读项目书才能敲定，而不是全平台的
    项目组；初审人与评审人则看自己持有任务的项目组。
    """
    if not (user and user.is_authenticated and group):
        return False
    if is_super_reviewer(user) and group.submissions.filter(
        status__in=ProjectSubmission.OPEN_STATUSES
    ).exists():
        return True
    # 两道关的任务在同一张表里，一次查询同时覆盖「我是这轮的初审人」与
    # 「我是这轮的评审人」。
    return ReviewTask.objects.filter(reviewer=user, submission__group=group).exists()
