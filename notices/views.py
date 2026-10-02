"""Notice list and detail views with explicit visibility querysets."""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET, require_POST

from . import services
from .models import Message, Notice
from .selectors import message_rows, message_target_url, unread_message_count
from .visibility import member_visible_notices, public_visible_notices


logger = logging.getLogger(__name__)


def public_list(request):
    notices = public_visible_notices().select_related("published_by")
    logger.info(
        "notice.list.view scope=public count=%s user=%s",
        notices.count(),
        request.user.get_username() if request.user.is_authenticated else "anonymous",
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return render(
        request,
        "notices/list.html",
        {
            "notices": notices,
            "page_title": _("公开通知"),
            "empty_message": _("暂时没有公开通知。"),
            "detail_namespace": "notices",
            "detail_name": "public_detail",
        },
    )


def public_detail(request, pk):
    notice = get_object_or_404(
        Notice.objects.select_related("published_by"),
        pk=pk,
        scope=Notice.PUBLIC,
    )
    logger.info(
        "notice.detail.view scope=public notice_id=%s user=%s",
        notice.pk,
        request.user.get_username() if request.user.is_authenticated else "anonymous",
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return render(
        request,
        "notices/detail.html",
        {
            "notice": notice,
            "back_url_name": "notices:public_list",
            "back_label": _("返回公开通知"),
        },
    )


@login_required
def internal_list(request):
    """「我的消息」：发给我的通知，未读的那些在列表里标出来。

    行由 ``selectors.message_rows`` 装配成固定形状，模板不直接碰模型——以后接
    @ 提及、评审通知时只扩展装配，这一页不用跟着改。
    """
    rows = message_rows(request.user)
    unread = unread_message_count(request.user)
    logger.info(
        "notice.messages.list count=%s unread=%s user=%s",
        len(rows),
        unread,
        request.user.get_username(),
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return render(
        request,
        "notices/message_list.html",
        {
            "rows": rows,
            "unread_count": unread,
        },
    )


@login_required
@require_POST
def mark_all_read(request):
    """「全部已读」：把当前可见的未读通知一次标掉，回列表页。

    POST 而不是链接：这是一次写操作，浏览器预取或爬虫不该触发它。
    """
    marked = services.mark_all_read(user=request.user)
    logger.info(
        "notice.messages.read_all username=%s marked=%s",
        request.user.get_username(),
        marked,
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    messages.success(request, _("已将全部消息标为已读。"))
    return redirect("member_notices:internal_list")


@login_required
@require_GET
def message_go(request, pk):
    """事件消息的点击去向：先标已读，再跳到目标页。

    走这一跳而不是把链接直接指向目标页：目标页（帖子、项目组）并不认识这条
    消息，「点开即已读」只能在中转处成立。
    """
    message = get_object_or_404(Message, pk=pk, recipient=request.user)
    target = message_target_url(message)
    if target is None:
        raise Http404
    services.mark_message_read(message=message)
    logger.info(
        "notice.messages.open message_id=%s kind=%s username=%s",
        message.pk,
        message.kind,
        request.user.get_username(),
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return redirect(target)


@login_required
def internal_detail(request, pk):
    notice = get_object_or_404(
        member_visible_notices(request.user).select_related("published_by"),
        pk=pk,
    )
    # 点进来就算读过：回执只影响未读样式与计数，重复进入不重复写。
    services.mark_read(user=request.user, notice=notice)
    logger.info(
        "notice.detail.view scope=internal notice_id=%s user=%s",
        notice.pk,
        request.user.get_username(),
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return render(
        request,
        "notices/detail.html",
        {
            "notice": notice,
            "back_url_name": "member_notices:internal_list",
            "back_label": _("返回我的消息"),
        },
    )
