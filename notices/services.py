"""「我的消息」的写操作：标已读。

高频、个人、幂等，所以不写审计（与登录、评审提交不同），由视图记日志。
「哪些通知算我的」仍归 :mod:`notices.visibility`，本模块不自己拼规则。
"""

from django.utils import timezone

from .models import Message, NoticeRead
from .visibility import member_visible_notices


def mark_read(*, user, notice):
    """把一条通知标为已读；已经读过就什么也不做。返回是否新写了回执。"""
    _receipt, created = NoticeRead.objects.get_or_create(user=user, notice=notice)
    return created


def mark_message_read(*, message):
    """把一条事件消息标为已读（点开跳转时）。返回是否新标了。"""
    if message.is_read:
        return False
    message.is_read = True
    message.read_at = timezone.now()
    message.save(update_fields=["is_read", "read_at"])
    return True


def mark_all_read(*, user):
    """把当前可见的未读通知与未读事件消息一次标掉，返回本次标了几条。

    通知那边与现状比对后只写缺的回执（``ignore_conflicts`` 挡住重复），
    事件消息一条 UPDATE 全清；重复提交是幂等的。
    """
    read_ids = NoticeRead.objects.filter(user=user).values("notice_id")
    unread = list(member_visible_notices(user).exclude(pk__in=read_ids))
    receipts = [NoticeRead(user=user, notice=notice) for notice in unread]
    if receipts:
        NoticeRead.objects.bulk_create(receipts, ignore_conflicts=True)
    marked_events = Message.objects.filter(recipient=user, is_read=False).update(
        is_read=True,
        read_at=timezone.now(),
    )
    return len(receipts) + marked_events
