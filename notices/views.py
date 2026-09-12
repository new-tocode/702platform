"""Notice list and detail views with explicit visibility querysets."""

import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from .models import Notice
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
            "page_title": "公开通知",
            "empty_message": "暂时没有公开通知。",
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
            "back_label": "返回公开通知",
        },
    )


@login_required
def internal_list(request):
    notices = member_visible_notices(request.user).select_related("published_by")
    logger.info(
        "notice.list.view scope=internal count=%s user=%s",
        notices.count(),
        request.user.get_username(),
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return render(
        request,
        "notices/list.html",
        {
            "notices": notices,
            "page_title": "内部通知",
            "empty_message": "暂时没有内部通知。",
            "detail_namespace": "member_notices",
            "detail_name": "internal_detail",
        },
    )


@login_required
def internal_detail(request, pk):
    notice = get_object_or_404(
        member_visible_notices(request.user).select_related("published_by"),
        pk=pk,
    )
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
            "back_label": "返回内部通知",
        },
    )
