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
    """一条申请对谁可见：排期表可进的人、申请人本人，以及该组当前的管理者。

    后两支都不能省：

    * 申请人把项目组转让出去以后就不再能管理该组，但他仍是这条申请的申请人，
      仍要能回来看自己写过的内容与讨论；
    * 组管理页会列出本组的申请，当前联系人点进去不能得到 403——他能管理这个组，
      就该看得到这个组的排期。「能看」不等于「能评论／能改／能关闭」，后三件事
      各有自己的判据。
    """
    if not (user and user.is_authenticated and defense_request):
        return False
    if can_access_schedule(user):
        return True
    if defense_request.applicant_id == user.pk:
        return True
    from projects.permissions import can_manage_group

    return can_manage_group(user, defense_request.group)


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

    能评论的只有三类评审资格、管理员与申请人本人；**当前联系人看一眼不算参与
    讨论**——他能看（见 :func:`can_view_request`），但评论仍按身份走。
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
    return can_access_schedule(user)


def can_close_request(user, defense_request):
    """申请人或管理员可以关闭；评审人只有评论权，没有关闭权。"""
    if not (user and user.is_authenticated and defense_request):
        return False
    if not defense_request.is_open:
        return False
    if defense_request.applicant_id == user.pk:
        return True
    return is_admin(user)
