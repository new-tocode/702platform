"""「我的消息」要的只读派生：把各来源装配成统一的行，以及未读计数。

行形状（:class:`MessageRow`）是页面与消息来源之间的接缝：视图与模板只认它，
来源增减只改这里的装配。来源有两类——

* **广播型通知**（``Notice``）：按可见集合实时查，已读来自 ``NoticeRead`` 回执；
* **事件型消息**（``Message`` 表）：发生时就落了行，标题／链接／说明在这里现取
  现算——帖子改了标题、轮次出了结论，消息里跟着变，不存副本。

只读不写，所以不叫 services；可见性判定仍归 :mod:`notices.visibility`，本模块
不自己拼规则。
"""

from dataclasses import dataclass
import logging
from datetime import datetime
from typing import NamedTuple

from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from .models import Message, Notice, NoticeRead
from .visibility import member_visible_notices


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MessageRow:
    """消息列表的一行。

    ``type_label`` 是来源类型（内部通知／公开通知／提及／评审…，见
    :data:`_TYPE_LABELS`）；``actor`` 是「来自」列（发布人、@ 你的人、申请人，
    没有合适的人就空着）；``context`` 是「说明」列（用户组名、帖子/评论、
    待初审…）；``at`` 既排序也显示。
    """

    type_label: str
    title: str
    url: str
    at: datetime
    actor: str
    context: str
    is_read: bool
    is_pinned: bool


class _EventContent(NamedTuple):
    """事件消息渲染出来的四个可显示字段；链接也由同一处现算。"""

    title: str
    url: str
    actor: str
    context: str


def _display_name(user):
    """一个人的显示名：姓名优先，没填回落账号；没有人给空串。"""
    if user is None:
        return ""
    profile = getattr(user, "profile", None)
    full_name = profile.full_name.strip() if profile else ""
    return full_name or user.get_username()


# --- 广播型通知 -------------------------------------------------------------


def _audience_text(notice):
    """通知的「说明」列：这份通知发给谁。"""
    if notice.scope == Notice.PUBLIC:
        return _("所有人")
    if notice.scope == Notice.CONTACTS:
        return _("仅项目组联系人")
    return ", ".join(group.name for group in notice.visible_groups.all())


def _notice_rows(user, read_ids):
    notices = (
        member_visible_notices(user)
        .select_related("published_by__profile")
        .prefetch_related("visible_groups")
    )
    return [
        MessageRow(
            type_label=(
                _("公开通知") if notice.scope == Notice.PUBLIC else _("内部通知")
            ),
            title=notice.title,
            url=reverse("member_notices:internal_detail", args=(notice.pk,)),
            at=notice.published_at,
            actor=_display_name(notice.published_by),
            context=_audience_text(notice),
            is_read=notice.pk in read_ids,
            is_pinned=notice.is_pinned,
        )
        for notice in notices
    ]


# --- 事件型消息 -------------------------------------------------------------


def _submission_title(submission):
    return _("%(name)s（第 %(round)s 轮）") % {
        "name": submission.group.name,
        "round": submission.round,
    }


def _group_url(group_id):
    return reverse("projects:group_detail", args=(group_id,))


def _mention_content(message):
    """@ 提及：标题是帖子，说明是帖子还是评论，链接落到那一楼。"""
    # 局部导入：notices 不在加载期依赖 discussion。
    from discussion.selectors import page_of_post

    post = message.post
    base = reverse("discussion:board", args=(post.board_id,))
    page = page_of_post(post)
    if message.comment_id:
        return _EventContent(
            post.title,
            f"{base}?page={page}#comment-{message.comment_id}",
            _display_name(message.actor),
            _("评论"),
        )
    return _EventContent(
        post.title,
        f"{base}?page={page}#post-{post.pk}",
        _display_name(message.actor),
        _("帖子"),
    )


def _review_content(message):
    """评审任务：待初审与待评审共用一套，靠 kind 区分说明。"""
    submission = message.submission
    return _EventContent(
        _submission_title(submission),
        _group_url(submission.group_id),
        "",
        _("待初审") if message.kind == Message.REVIEW_PRELIMINARY else _("待评审"),
    )


def _review_result_content(message):
    """评审结论：状态现取，跟着轮次走。"""
    # 局部导入：notices 不在加载期依赖 reviews。
    from reviews.models import ProjectSubmission

    submission = message.submission
    return _EventContent(
        _submission_title(submission),
        _group_url(submission.group_id),
        "",
        _("已通过") if submission.status == ProjectSubmission.APPROVED else _("需修改"),
    )


def _join_request_content(message):
    """有人申请入组：给联系人，去项目组详情页处理。"""
    join_request = message.join_request
    return _EventContent(
        join_request.group.name,
        _group_url(join_request.group_id),
        _display_name(join_request.applicant),
        _("待你审核"),
    )


def _join_result_content(message):
    """入组申请的结果：给申请人。"""
    join_request = message.join_request
    # 局部导入：notices 不在加载期依赖 projects。
    from projects.models import GroupJoinRequest

    return _EventContent(
        join_request.group.name,
        _group_url(join_request.group_id),
        _display_name(message.actor),
        _("已通过") if join_request.status == GroupJoinRequest.APPROVED else _("已拒绝"),
    )


def _create_request_content(message):
    """有人申请创建项目组：给管理员，去评审页处理。"""
    create_request = message.create_request
    return _EventContent(
        create_request.name,
        reverse("reviews:queue"),
        _display_name(create_request.applicant),
        _("待审核"),
    )


def _create_result_content(message):
    """建组申请的结果：给申请人；通过后直接落到新组。"""
    # 局部导入：notices 不在加载期依赖 projects。
    from projects.models import GroupCreateRequest

    create_request = message.create_request
    approved = create_request.status == GroupCreateRequest.APPROVED
    if approved and create_request.created_group_id:
        url = _group_url(create_request.created_group_id)
    else:
        url = reverse("projects:group_list")
    return _EventContent(
        create_request.name,
        url,
        _display_name(message.actor),
        _("已通过") if approved else _("已拒绝"),
    )


#: 类型列的标签；模块级只写一次，取用时按当时的语言求值。
_TYPE_LABELS = {
    Message.MENTION: _("提及"),
    Message.REVIEW_PRELIMINARY: _("评审"),
    Message.REVIEW: _("评审"),
    Message.REVIEW_RESULT: _("评审结果"),
    Message.JOIN_REQUEST: _("入组申请"),
    Message.JOIN_RESULT: _("入组结果"),
    Message.CREATE_REQUEST: _("建组申请"),
    Message.CREATE_RESULT: _("建组结果"),
}

#: 每种 kind 怎么渲染成行；接新来源时在这里加一条。
_CONTENT_BUILDERS = {
    Message.MENTION: _mention_content,
    Message.REVIEW_PRELIMINARY: _review_content,
    Message.REVIEW: _review_content,
    Message.REVIEW_RESULT: _review_result_content,
    Message.JOIN_REQUEST: _join_request_content,
    Message.JOIN_RESULT: _join_result_content,
    Message.CREATE_REQUEST: _create_request_content,
    Message.CREATE_RESULT: _create_result_content,
}


def _event_rows(user):
    messages = Message.objects.filter(recipient=user).select_related(
        "actor__profile",
        "post",
        "comment",
        "submission__group",
        "join_request__group",
        "join_request__applicant__profile",
        "create_request__applicant__profile",
    )
    rows = []
    for message in messages:
        builder = _CONTENT_BUILDERS.get(message.kind)
        if builder is None:
            # 数据里出现了不认识的行（比如降级部署留下的），不该让整页 500。
            logger.warning(
                "notice.messages.unknown_kind message_id=%s kind=%s",
                message.pk,
                message.kind,
            )
            continue
        content = builder(message)
        rows.append(
            MessageRow(
                type_label=_TYPE_LABELS[message.kind],
                title=content.title,
                # 事件消息先走一跳 message_go：目标页（帖子、项目组）并不认识
                # 这条消息，「点开即已读」只能在中转处成立。通知走详情页，
                # 那边的 GET 自己会写回执。
                url=reverse("member_notices:message_go", args=(message.pk,)),
                at=message.created_at,
                actor=content.actor,
                context=content.context,
                is_read=message.is_read,
                is_pinned=False,
            )
        )
    return rows


# --- 对外的两个口径 ---------------------------------------------------------


def message_rows(user):
    """我的消息的全部行：置顶通知在最前，其余按发生时间倒序混排。"""
    if not (user and user.is_authenticated):
        return ()
    read_ids = set(
        NoticeRead.objects.filter(user=user).values_list("notice_id", flat=True)
    )
    rows = [*_notice_rows(user, read_ids), *_event_rows(user)]
    rows.sort(key=lambda row: (row.is_pinned, row.at), reverse=True)
    return tuple(rows)


def unread_message_count(user):
    """未读消息数 = 未读通知 + 未读事件消息；列表页与成员中心提醒共用。"""
    if not (user and user.is_authenticated):
        return 0
    read_ids = NoticeRead.objects.filter(user=user).values("notice_id")
    unread_notices = member_visible_notices(user).exclude(pk__in=read_ids).count()
    unread_events = Message.objects.filter(recipient=user, is_read=False).count()
    return unread_notices + unread_events


def message_target_url(message):
    """一条事件消息跳转的最终去向；kind 不认识时给 ``None``（调用方 404）。"""
    builder = _CONTENT_BUILDERS.get(message.kind)
    return builder(message).url if builder else None
