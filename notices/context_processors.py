"""顶栏「成员中心」的未读角标要的那个数。

基底上下文处理器，**每一页**都算一次：角标长在顶栏上，而顶栏属于每一页。数字本身
不在这里算——口径仍是 :func:`notices.selectors.unread_message_count` 一处，与成员
中心那一页的提醒条、入口徽标是同一个数（那两处由 :mod:`notices.panels` 装配）。
"""

from .selectors import unread_message_count


def unread_messages(request):
    """未读消息数，给 ``base.html`` 的顶栏用；未登录与强制改密期间一律 0。

    强制改密那一段刻意给 0：那时成员中心里的入口一个都进不去
    （``ForcePasswordChangeMiddleware`` 一律拦回改密页），角标点不出东西，
    就跟着入口一起收起来——与 ``core.registry`` 判入口可见性是同一个条件。
    """
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {"unread_messages": 0}
    if getattr(user, "must_change_password", False):
        return {"unread_messages": 0}
    return {"unread_messages": unread_message_count(user)}
