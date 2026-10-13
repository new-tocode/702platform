"""成员侧的通知、消息与私信页面。

可见性一律走 :mod:`notices.visibility` 的查询集（取不到就是 404）；私信一律按
``recipient=request.user`` 取行——本模块没有 ``permissions.py``，成员页的门槛只有
``@login_required`` 加上「这一条是不是我的」。
"""

import logging

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from . import services
from .forms import DirectMessageForm
from .models import Message, Notice
from .panels import direct_compose_context
from .selectors import (
    display_name,
    message_rows,
    message_target_url,
    unread_message_count,
)
from .visibility import member_visible_notices, public_visible_notices


logger = logging.getLogger(__name__)
User = get_user_model()


def _request_id(request):
    return getattr(request, "request_id", "-")


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
    # 页面上的私信浮动窗（私信行上的「快速回信」要用它）；表单由 notices 自己给。
    return render(
        request,
        "notices/message_list.html",
        {
            "rows": rows,
            "unread_count": unread,
            **direct_compose_context(),
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


# --- 私信 -------------------------------------------------------------------


def _direct_recipient(user_id):
    """私信的收信人：只有仍在册的成员收得到（与只读资料页同一道门）。"""
    return get_object_or_404(User.objects.filter(is_active=True), pk=user_id)


def _back_to(request):
    """发完、删完回哪儿：表单带的 ``next``（同站才认），没有就回「我的消息」。

    与 accounts 的改密页同一个口径：``next`` 由页面给，服务端只接受站内地址。
    """
    requested = request.POST.get("next") or request.GET.get("next")
    if requested and url_has_allowed_host_and_scheme(
        requested,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return requested
    return reverse("member_notices:internal_list")


@login_required
@require_http_methods(["GET", "POST"])
def direct_compose(request, user_id):
    """写私信：GET 出表单，POST 发送。

    一个地址两种外壳：**整页**（没有脚本时从成员资料页的「私信」、消息行上的
    「快速回信」进来）与页面上的**小浮动窗**（同一个表单装在
    ``includes/direct_compose.html`` 的 ``<dialog>`` 里，脚本把它的 action 指到
    这一个地址）。成功一律 PRG + flash——窗口所在的那一页重新加载，窗口自己就
    没了；失败时重渲染这一页，写过的正文还在。
    """
    recipient = _direct_recipient(user_id)
    back_to = _back_to(request)
    if recipient.pk == request.user.pk:
        # 页面上的入口对自己不显示（模板那一层），这里是真正的边界。
        # 业务拒绝不是 4xx：给一句话，回原来那页。
        messages.error(request, _("不能给自己发私信。"))
        return redirect(back_to)

    if request.method == "POST":
        form = DirectMessageForm(request.POST)
        if form.is_valid():
            message = services.send_direct_message(
                sender=request.user,
                recipient=recipient,
                body=form.cleaned_data["body"],
            )
            logger.info(
                "notice.messages.direct.send message_id=%s sender=%s recipient_id=%s chars=%s",
                message.pk,
                request.user.get_username(),
                recipient.pk,
                len(form.cleaned_data["body"]),
                extra={"request_id": _request_id(request)},
            )
            messages.success(request, _("私信已发送。"))
            return redirect(back_to)
        logger.warning(
            "notice.messages.direct.reject sender=%s recipient_id=%s errors=%s",
            request.user.get_username(),
            recipient.pk,
            form.errors.as_json(),
            extra={"request_id": _request_id(request)},
        )
    else:
        form = DirectMessageForm()

    return render(
        request,
        "notices/direct_compose.html",
        {
            "direct_form": form,
            "recipient": recipient,
            "recipient_display_name": display_name(recipient),
            "back_to": back_to,
        },
    )


def _own_direct_message(request, pk, *, related):
    """按收件人取一条私信：不是我的、不是私信、正文缺了，都当取不到（404）。"""
    message = get_object_or_404(
        related,
        pk=pk,
        recipient=request.user,
        kind=Message.DIRECT,
    )
    if message.direct_message_id is None:
        raise Http404
    return message


@login_required
@require_GET
def direct_detail(request, pk):
    """私信全文。点开即已读，但**读完不消失**——要它走，得自己在这一页删。"""
    message = _own_direct_message(
        request,
        pk,
        related=Message.objects.select_related("direct_message__sender__profile"),
    )
    services.mark_message_read(message=message)
    direct = message.direct_message
    logger.info(
        "notice.messages.direct.view message_id=%s username=%s",
        message.pk,
        request.user.get_username(),
        extra={"request_id": _request_id(request)},
    )
    return render(
        request,
        "notices/direct_detail.html",
        {
            "message": message,
            "direct": direct,
            "sender_display_name": display_name(direct.sender),
            **direct_compose_context(),
        },
    )


@login_required
@require_POST
def direct_delete(request, pk):
    """收件人主动删除一条私信：正文与那条通知一起走。"""
    message = _own_direct_message(
        request,
        pk,
        related=Message.objects.select_related("direct_message"),
    )
    services.delete_direct_message(message=message)
    logger.info(
        "notice.messages.direct.delete message_id=%s username=%s",
        pk,
        request.user.get_username(),
        extra={"request_id": _request_id(request)},
    )
    messages.success(request, _("私信已删除。"))
    return redirect("member_notices:internal_list")


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
