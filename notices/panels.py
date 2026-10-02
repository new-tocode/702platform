"""成员中心里消息那一半的上下文装配。

与 :mod:`reviews.panels` 同一个模式：页面（accounts 的 ``member_home``）只负责摆，
「我这一块显示什么」由各应用自己挑好。未读计数走 :mod:`notices.selectors` 的唯一
口径，没有未读时是 0，模板据此不渲染提醒。
"""

from .selectors import unread_message_count


def member_home_context(*, user):
    """「我的消息」的未读计数，供成员中心的提醒条与入口徽标取用。"""
    return {"unread_messages": unread_message_count(user)}
