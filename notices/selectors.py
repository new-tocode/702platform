"""「我的消息」要的只读派生：把各来源装配成统一的行，以及未读计数。

行形状（:class:`MessageRow`）是页面与消息来源之间的接缝：视图与模板只认它，
来源增减只改这里的装配。来源有两类——

* **广播型通知**（``Notice``）：按可见集合实时查，已读来自 ``NoticeRead`` 回执；
* **事件型消息**（``Message`` 表）：发生时就落了行，标题／链接／说明在这里现取
  现算——帖子改了标题、轮次出了结论、申请被处理了，消息里跟着变，不存副本。

只读不写，所以不叫 services；可见性判定仍归 :mod:`notices.visibility`，本模块
不自己拼规则。
"""

from dataclasses import dataclass
import logging
from datetime import datetime
from typing import NamedTuple

from django.urls import reverse
from django.utils.text import Truncator
from django.utils.translation import gettext_lazy as _

from .models import Message, Notice, NoticeRead
from .visibility import member_visible_notices


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MessageRow:
    """消息列表的一行。

    ``type_label`` 是来源类型（内部通知／公开通知／提及／评审…，见
    :data:`_TYPE_LABELS`）；``actor`` 是「来自」列（发布人、@ 你的人、申请人，
    没有合适的人就空着）；``context`` 是「说明」列——它不只有状态：通知放受众、
    提及放帖子/评论、评论与私信放正文节选，审批类（待审核、已由 X 审核通过…）
    才放状态；``at`` 既排序也显示。

    ``reply_to_id`` 非空时行上多一个「快速回信」（值是要回给谁的账号 id，今天只有
    私信会给）；``url`` 照旧是这一行点开之后去哪。
    """

    type_label: str
    title: str
    url: str
    at: datetime
    actor: str
    context: str
    is_read: bool
    is_pinned: bool
    reply_to_id: int | None = None


class _EventContent(NamedTuple):
    """事件消息渲染出来的四个可显示字段；链接也由同一处现算。

    渲染函数返回 ``None`` 表示这一行渲染不出来（来源缺了），由调用方跳过——
    详情页与列表都不该为一颗坏行整页 500。
    """

    title: str
    url: str
    actor: str
    context: str
    reply_to_id: int | None = None


def display_name(user):
    """一个人的显示名：姓名优先，没填回落账号；没有人给空串。

    对外的公开函数：装配行要用它，页面（私信页头与浮动窗的收件人）也要用同一份口径。
    """
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
            actor=display_name(notice.published_by),
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


def _discussion_url(message, anchor):
    """帖子所在板块的那一页，带 ``#post-N`` / ``#comment-N`` 锚点。"""
    # 局部导入：notices 不在加载期依赖 discussion。
    from discussion.selectors import page_of_post

    post = message.post
    base = reverse("discussion:board", args=(post.board_id,))
    return f"{base}?page={page_of_post(post)}#{anchor}"


def _mention_content(message):
    """@ 提及：标题是帖子，说明是帖子还是评论，链接落到那一楼。"""
    post = message.post
    if message.comment_id:
        return _EventContent(
            post.title,
            _discussion_url(message, f"comment-{message.comment_id}"),
            display_name(message.actor),
            _("评论"),
        )
    return _EventContent(
        post.title,
        _discussion_url(message, f"post-{post.pk}"),
        display_name(message.actor),
        _("帖子"),
    )


#: 「说明」列里的节选上限（含末尾的省略号）：一格摘要，全文点开就是。
#: 评论与私信共用——两者都只是让人认出「说的是哪一句」。
_EXCERPT_CHARS = 40


def _comment_content(message):
    """有人评论了你的帖子：标题是帖子，说明是那条评论的节选。"""
    return _EventContent(
        message.post.title,
        _discussion_url(message, f"comment-{message.comment_id}"),
        display_name(message.actor),
        Truncator(" ".join(message.comment.content.split())).chars(
            _EXCERPT_CHARS, truncate="…"
        ),
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


def _decision_status(record, *, pending):
    """审批类消息的「说明」格：等处理时是待办，有结论后连处理人一起报出来。

    ``record`` 是 ``GroupCreateRequest`` 或 ``GroupJoinRequest``——两者共用
    ``PENDING`` / ``APPROVED`` 两个状态常量与 ``decided_by``。

    结论与处理人都**现取现算**（与标题同一条规矩，见 ``notices/README.md`` §2）：
    处理掉之后，我这一行的「待审核」跟着变成「已由 X 审核通过」，既不用回填消息，
    也不会让「谁处理的」在消息里另存一份。处理人正是收件人自己也照写名字——这条
    消息本来就可能是别人（另一位管理员、换过手的联系人）替你处理的。

    ``decided_by`` 为空的行（绕过服务层造的）退回不带名字的结论，不拼出
    「已由  审核通过」这种半句话。
    """
    if record.status == record.PENDING:
        return pending
    name = display_name(record.decided_by)
    if record.status == record.APPROVED:
        return _("已由 %(name)s 审核通过") % {"name": name} if name else _("已通过")
    return _("已被 %(name)s 拒绝") % {"name": name} if name else _("已拒绝")


def _join_request_content(message):
    """有人申请入组：给联系人，去项目组详情页处理；状态跟着申请走。"""
    join_request = message.join_request
    return _EventContent(
        join_request.group.name,
        _group_url(join_request.group_id),
        display_name(join_request.applicant),
        _decision_status(join_request, pending=_("待你审核")),
    )


def _join_result_content(message):
    """入组申请的结果：给申请人。"""
    join_request = message.join_request
    # 局部导入：notices 不在加载期依赖 projects。
    from projects.models import GroupJoinRequest

    return _EventContent(
        join_request.group.name,
        _group_url(join_request.group_id),
        display_name(message.actor),
        _("已通过") if join_request.status == GroupJoinRequest.APPROVED else _("已拒绝"),
    )


def _create_request_content(message):
    """有人申请创建项目组：给管理员，去评审页处理；状态跟着申请走。

    别的管理员先处理掉之后，这一行从「待审核」变成「已由 X 审核通过」——那条申请
    已经不在队列里了，收件人光看这一行就该知道，不必点进去扑个空。
    """
    create_request = message.create_request
    return _EventContent(
        create_request.name,
        reverse("reviews:queue"),
        display_name(create_request.applicant),
        _decision_status(create_request, pending=_("待审核")),
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
        display_name(message.actor),
        _("已通过") if approved else _("已拒绝"),
    )


def direct_reply_target(direct):
    """这条私信能回给谁：发信人**仍在册**才有得回，否则是 ``None``。

    注销（硬删，``sender`` 变 ``None``）与**停用**都算没有可回的人。停用这条尤其要
    跟住：本平台的账号退场口径是停用（见 ``../docs/更新维护/开发与部署.md`` §6），
    而写私信那道门的条件是「收信人在册」——两边用同一个条件，行上的按钮才不会点出 404
    （``direct_compose`` 对停用账号给的就是 404）。
    """
    sender = direct.sender
    if sender is None or not sender.is_active:
        return None
    return sender.pk


def _direct_content(message):
    """有人给你发了私信：标题是「有人给你发了一条私信」，说明是正文的节选。

    点开落到私信详情页（``member_notices:direct_detail``）——那是全文的家。行上的
    「快速回信」回给发信人，能不能回由 :func:`direct_reply_target` 说了算。
    """
    direct = message.direct_message
    if direct is None:
        # 没有正文的私信行（绕过 services 建的）：不给一条点不到、点开也没有内容的行。
        return None
    return _EventContent(
        _("向你发送了一条私信"),
        reverse("member_notices:direct_detail", args=(message.pk,)),
        display_name(direct.sender),
        Truncator(" ".join(direct.body.split())).chars(_EXCERPT_CHARS, truncate="…"),
        reply_to_id=direct_reply_target(direct),
    )


#: 类型列的标签；模块级只写一次，取用时按当时的语言求值。
_TYPE_LABELS = {
    Message.MENTION: _("提及"),
    Message.COMMENT: _("评论"),
    Message.DIRECT: _("私信"),
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
    Message.COMMENT: _comment_content,
    Message.DIRECT: _direct_content,
    Message.REVIEW_PRELIMINARY: _review_content,
    Message.REVIEW: _review_content,
    Message.REVIEW_RESULT: _review_result_content,
    Message.JOIN_REQUEST: _join_request_content,
    Message.JOIN_RESULT: _join_result_content,
    Message.CREATE_REQUEST: _create_request_content,
    Message.CREATE_RESULT: _create_result_content,
}


def _renderable_messages(user):
    """我收到的、真渲染得出来的事件消息行。

    今天唯一被排除的是「有 ``kind=direct`` 但没有正文」的坏行（绕过写入函数建的）：
    :func:`_event_rows` 渲染不出来它，计数若还算上它，就会「提醒条说 1 条未读、
    「我的消息」里却没有任何一行可点」——同一个数字不该有两处口径。
    """
    return Message.objects.filter(recipient=user).exclude(
        kind=Message.DIRECT,
        direct_message__isnull=True,
    )


def _event_rows(user):
    messages = _renderable_messages(user).select_related(
        "actor__profile",
        "post",
        "comment",
        "submission__group",
        "join_request__group",
        "join_request__applicant__profile",
        "join_request__decided_by__profile",
        "create_request__applicant__profile",
        "create_request__decided_by__profile",
        "direct_message__sender__profile",
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
        if content is None:
            # 取数时已经滤掉已知的坏行（见 _renderable_messages）；这里兜住「渲染函数
            # 自己返回 None」那种将来才会有的情况——同样跳过，别让整页 500。
            logger.warning(
                "notice.messages.missing_source message_id=%s kind=%s",
                message.pk,
                message.kind,
            )
            continue
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
                reply_to_id=content.reply_to_id,
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
    unread_events = _renderable_messages(user).filter(is_read=False).count()
    return unread_notices + unread_events


def message_target_url(message):
    """一条事件消息跳转的最终去向；kind 不认识、或来源缺失时给 ``None``（调用方 404）。"""
    builder = _CONTENT_BUILDERS.get(message.kind)
    if builder is None:
        return None
    content = builder(message)
    return content.url if content else None
