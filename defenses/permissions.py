"""谁可以发起、查看、修改、评论与关闭线下模拟答辩申请。

判定放在这里而不是视图里，模板与视图两边都从这里取口径（双层权限控制：
模板隐藏入口只影响展示，真正的边界在视图的第二道校验）。

排期表与申请详情对**所有登录成员**开放；评论只给该申请所属项目组的成员、
申请人本人，以及三种「评审」资格或管理员。后者的口径**不在这里重写**，问的是
:func:`reviews.permissions.can_open_queue`。能不能管理项目组问的是
:func:`projects.permissions.can_manage_group`。
"""

from core.permissions import is_admin

from .models import DefenseRequest


def can_open_reviews(user):
    """三种评审资格或管理员；与「评审」页入口同一个判据。"""
    from reviews.permissions import can_open_queue

    return can_open_queue(user)


def can_create_request(user, group):
    """发起申请的人：能管理这个项目组的人（该组联系人，或管理员）。"""
    from projects.permissions import can_manage_group

    return can_manage_group(user, group)


def can_access_schedule(user):
    """排期表的准入：所有登录成员。

    排期表是社团内部的公开安排表，普通成员也能查看；评论权限另见
    :func:`can_comment`，不跟着这里一起放开。
    """
    return bool(user and user.is_authenticated)


def can_view_request(user, defense_request):
    """一条申请对谁可见：排期表可进的登录成员都能看详情。

    查看与评论已经是两个口径：非本组的普通成员能看讨论，但发不了言。
    """
    return bool(user and user.is_authenticated and defense_request)


def can_edit_request(user, defense_request):
    """只有申请人能改正文，且只在「安排中」时能改。"""
    return bool(
        user
        and user.is_authenticated
        and defense_request
        and defense_request.is_open
        and defense_request.applicant_id == user.pk
    )


def can_comment(user, defense_request):
    """关闭即归档：已确定的申请不再接受新评论。

    能评论的是该申请所属项目组的成员、申请人本人，以及三类评审资格或管理员。
    其他项目组的普通成员可以看排期与讨论，但发不了言。
    """
    if not (
        user
        and user.is_authenticated
        and defense_request
        and defense_request.is_open
    ):
        return False
    if defense_request.applicant_id == user.pk:
        return True
    if defense_request.group.members.filter(pk=user.pk).exists():
        return True
    return can_open_reviews(user)


def can_close_request(user, defense_request):
    """申请人或管理员可以关闭；评审人只有评论权，没有关闭权。"""
    if not (user and user.is_authenticated and defense_request):
        return False
    if not defense_request.is_open:
        return False
    if defense_request.applicant_id == user.pk:
        return True
    return is_admin(user)
