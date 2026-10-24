"""谁可以发起、查看、修改、评论与关闭线下模拟答辩申请。

判定放在这里而不是视图里，模板与视图两边都从这里取口径（双层权限控制：
模板隐藏入口只影响展示，真正的边界在视图的第二道校验）。

三种「评审」资格与管理员的口径**不在这里重写**：能不能进排期表问的是
:func:`reviews.permissions.can_open_queue`（它与「评审」页入口同一个判据），
能不能管理项目组问的是 :func:`projects.permissions.can_manage_group`。
"""

from core.permissions import is_admin

from .models import DefenseRequest


def can_create_request(user, group):
    """发起申请的人：能管理这个项目组的人（该组联系人，或管理员）。"""
    from projects.permissions import can_manage_group

    return can_manage_group(user, group)


def can_access_schedule(user):
    """排期表的准入：三种评审资格中的任意一种，或管理员。

    与「评审」页入口同一个口径——入口就长在那一页上，能进那一页的人就能进
    排期表，不必再定义第二种「谁算评审」。
    """
    from reviews.permissions import can_open_queue

    return can_open_queue(user)


def can_view_request(user, defense_request):
    """一条申请对谁可见：排期表可进的人，以及这条申请的申请人本人。

    申请人那一支不能省：联系人把项目组转让出去以后就不再能管理该组，但他仍是
    这条申请的申请人，仍要能回来看自己写过的内容与讨论。
    """
    if not (user and user.is_authenticated and defense_request):
        return False
    if can_access_schedule(user):
        return True
    return defense_request.applicant_id == user.pk


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
    """关闭即归档：已确定的申请不再接受新评论。"""
    return bool(
        defense_request
        and defense_request.is_open
        and can_view_request(user, defense_request)
    )


def can_close_request(user, defense_request):
    """申请人或管理员可以关闭；评审人只有评论权，没有关闭权。"""
    if not (user and user.is_authenticated and defense_request):
        return False
    if not defense_request.is_open:
        return False
    if defense_request.applicant_id == user.pk:
        return True
    return is_admin(user)
