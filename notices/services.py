"""「我的消息」的写操作：标已读。

高频、个人、幂等，所以不写审计（与登录、评审提交不同），由视图记日志。
「哪些通知算我的」仍归 :mod:`notices.visibility`，本模块不自己拼规则。
"""

from .models import NoticeRead
from .visibility import member_visible_notices


def mark_read(*, user, notice):
    """把一条通知标为已读；已经读过就什么也不做。返回是否新写了回执。"""
    _receipt, created = NoticeRead.objects.get_or_create(user=user, notice=notice)
    return created


def mark_all_read(*, user):
    """把当前可见的未读通知一次标掉，返回本次标了几条。

    与现状比对后只写缺的那些，重复提交是幂等的；``ignore_conflicts`` 挡住同一个
    人开两个标签页同时提交时的撞车——撞上的那条已被另一路写过，跳过即可。
    """
    read_ids = NoticeRead.objects.filter(user=user).values("notice_id")
    unread = list(member_visible_notices(user).exclude(pk__in=read_ids))
    if not unread:
        return 0
    NoticeRead.objects.bulk_create(
        [NoticeRead(user=user, notice=notice) for notice in unread],
        ignore_conflicts=True,
    )
    return len(unread)
