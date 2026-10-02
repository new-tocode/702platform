"""「我的消息」的写操作：标已读。

高频、个人、幂等，所以不写审计（与登录、评审提交不同），由视图记日志。
「哪些通知算我的」仍归 :mod:`notices.visibility`，本模块不自己拼规则。
"""

from django.utils import timezone

from .models import Message, NoticeRead
from .visibility import member_visible_notices


def sync_mention_messages(*, post, comment, actor, mentioned_users):
    """让「这条帖子/评论上的提及消息」与 ``mentioned_users`` 对齐。

    帖子被编辑后 @ 的人可能变了，所以这里做的是对齐而不是只管新增：缺的写
    消息、多的删消息。自己 @ 自己不发。返回新写了几条。

    ``comment=None`` 表示帖子正文上的提及；评论上的提及以评论为界，互不影响。
    """
    wanted = {user.pk: user for user in mentioned_users if user.pk != actor.pk}
    scope = {"kind": Message.MENTION, "post": post, "comment": comment}
    existing = {
        message.recipient_id: message
        for message in Message.objects.filter(**scope)
    }

    stale = [existing[pk].pk for pk in set(existing) - set(wanted)]
    if stale:
        Message.objects.filter(pk__in=stale).delete()

    created = [
        Message(recipient=user, actor=actor, **scope)
        for pk, user in wanted.items()
        if pk not in existing
    ]
    if created:
        Message.objects.bulk_create(created)
    return len(created)


def clear_mention_messages(*, comment):
    """评论被（软）删除后，它在别人消息里留下的提及一并撤掉。

    软删除的评论内容还留在库里，但界面上已经看不到了——消息点过去也只会看到
    「该评论已删除」，不如不提醒。
    """
    Message.objects.filter(kind=Message.MENTION, comment=comment).delete()


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
