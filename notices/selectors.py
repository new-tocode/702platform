"""「我的消息」要的只读派生：可见通知装配成统一的行形状，以及未读计数。

行形状（:class:`MessageRow`）是页面与消息来源之间的接缝：视图与模板只认它，
以后接帖子 @ 提及、评审通知时只在这里扩展装配，列表页不用跟着改。公开通知
（``scope=public``）不进这里——那是公告栏，没有「投递给我」的语义。

只读不写，所以不叫 services；可见性判定仍归 :mod:`notices.visibility`，
本模块不自己拼规则。
"""

from dataclasses import dataclass
from datetime import datetime

from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from .models import Notice, NoticeRead
from .visibility import member_visible_notices


@dataclass(frozen=True)
class MessageRow:
    """消息列表的一行。

    ``type_label`` 现在只有「内部通知」一个值，保留它是为了后续来源（@ 提及、
    评审通知）进来时模板不用动；``audience`` 是范围列的显示文本；``is_read``
    由回执表算出来。
    """

    type_label: str
    title: str
    url: str
    published_at: datetime
    publisher: str
    audience: str
    is_read: bool
    is_pinned: bool


def _publisher_name(notice):
    """发布人的显示名：姓名优先，没填回落账号（与详情页同口径）。"""
    profile = getattr(notice.published_by, "profile", None)
    full_name = profile.full_name.strip() if profile else ""
    return full_name or notice.published_by.get_username()


def _audience_text(notice):
    """范围列的显示文本。

    仅联系人通知没有用户组，写死一句「仅项目组联系人」；内部通知列出
    ``visible_groups`` 的组名，多个用逗号分隔（与后台 ``visible_groups_display``
    同口径，只是那边是给管理员看的）。
    """
    if notice.scope == Notice.CONTACTS:
        return _("仅项目组联系人")
    return ", ".join(group.name for group in notice.visible_groups.all())


def message_rows(user):
    """我的消息的全部行：可见通知，按通知的既有排序（置顶优先、新到旧）。

    两张表各取一次（可见通知、我的回执），在 Python 里装配——行数是社团规模，
    比给每行单独查一次已读状态省。``prefetch_related`` 让范围文本不在循环里
    逐条查组。
    """
    if not (user and user.is_authenticated):
        return ()
    notices = (
        member_visible_notices(user)
        .select_related("published_by__profile")
        .prefetch_related("visible_groups")
    )
    read_ids = set(
        NoticeRead.objects.filter(user=user).values_list("notice_id", flat=True)
    )
    return tuple(
        MessageRow(
            type_label=_("内部通知"),
            title=notice.title,
            url=reverse("member_notices:internal_detail", args=(notice.pk,)),
            published_at=notice.published_at,
            publisher=_publisher_name(notice),
            audience=_audience_text(notice),
            is_read=notice.pk in read_ids,
            is_pinned=notice.is_pinned,
        )
        for notice in notices
    )


def unread_message_count(user):
    """未读消息数 = 可见通知 − 已读回执。

    列表页与成员中心的提醒共用这一个口径，不许各算各的。
    """
    if not (user and user.is_authenticated):
        return 0
    read_ids = NoticeRead.objects.filter(user=user).values("notice_id")
    return member_visible_notices(user).exclude(pk__in=read_ids).count()
