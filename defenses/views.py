"""成员侧线下模拟答辩：排期表、申请、详情、评论与关闭。"""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from core.permissions import require
from projects.models import ProjectGroup

from . import permissions, selectors
from .forms import DefenseCommentForm, DefenseRequestForm
from .services import (
    DefenseError,
    add_comment,
    close_request,
    create_request,
    update_request,
)


logger = logging.getLogger(__name__)


def _request_id(request):
    return getattr(request, "request_id", "-")


@login_required
def schedule(request):
    """「线下答辩」页：「安排中」与「已确定」两块，各自按时间倒序。"""
    require(
        request,
        permissions.can_access_schedule(request.user),
        "defenses.schedule.denied",
        reason="no_schedule_access",
    )
    open_requests = selectors.open_requests()
    closed_requests = selectors.closed_requests()
    logger.info(
        "defenses.schedule.view open=%s closed=%s user=%s",
        open_requests.count(),
        closed_requests.count(),
        request.user.get_username(),
        extra={"request_id": _request_id(request)},
    )
    return render(
        request,
        "defenses/schedule.html",
        {
            "open_requests": open_requests,
            "closed_requests": closed_requests,
        },
    )


@login_required
def request_create(request, group_pk):
    """从项目组管理页进来，给这个组发起一条答辩申请。"""
    group = get_object_or_404(
        ProjectGroup.objects.select_related("leader__profile"),
        pk=group_pk,
    )
    require(
        request,
        permissions.can_create_request(request.user, group),
        "defenses.request.create.denied",
        group_id=group.pk,
    )
    form = DefenseRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            defense_request = create_request(
                group=group,
                applicant=request.user,
                content=form.cleaned_data["content"],
                request=request,
            )
        except DefenseError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(
                request,
                _("已提交线下模拟答辩申请，评审人可在「线下答辩」中查看并讨论。"),
            )
            return redirect("defenses:detail", pk=defense_request.pk)
        return redirect("projects:group_manage", pk=group.pk)

    return render(
        request,
        "defenses/request_form.html",
        {"form": form, "group": group},
    )


@login_required
def detail(request, pk):
    """一条申请的详情：正文、完整讨论，以及当前身份可做的动作。"""
    defense_request = get_object_or_404(selectors.request_detail_queryset(), pk=pk)
    require(
        request,
        permissions.can_view_request(request.user, defense_request),
        "defenses.request.view.denied",
        defense_id=defense_request.pk,
    )
    can_edit = permissions.can_edit_request(request.user, defense_request)
    can_comment = permissions.can_comment(request.user, defense_request)
    can_close = permissions.can_close_request(request.user, defense_request)
    logger.info(
        "defenses.request.view request_id=%s status=%s user=%s",
        defense_request.pk,
        defense_request.status,
        request.user.get_username(),
        extra={"request_id": _request_id(request)},
    )
    return render(
        request,
        "defenses/detail.html",
        {
            "defense_request": defense_request,
            "comments": defense_request.comments.all(),
            "can_edit": can_edit,
            "can_comment": can_comment,
            "can_close": can_close,
            "can_browse_schedule": permissions.can_access_schedule(request.user),
            "edit_form": DefenseRequestForm(instance=defense_request) if can_edit else None,
            "comment_form": DefenseCommentForm() if can_comment else None,
        },
    )


@login_required
@require_POST
def request_edit(request, pk):
    """申请人修改正文：成功后自动多一条「申请者修改了答辩申请」。"""
    defense_request = get_object_or_404(selectors.request_detail_queryset(), pk=pk)
    require(
        request,
        permissions.can_edit_request(request.user, defense_request),
        "defenses.request.edit.denied",
        defense_id=defense_request.pk,
    )
    form = DefenseRequestForm(request.POST, instance=defense_request)
    if form.is_valid():
        try:
            _updated, changed = update_request(
                defense_request=defense_request,
                content=form.cleaned_data["content"],
                actor=request.user,
                request=request,
            )
        except DefenseError as exc:
            messages.error(request, str(exc))
        else:
            if changed:
                messages.success(request, _("答辩申请已更新。"))
            else:
                messages.info(request, _("内容没有变化，未产生修改记录。"))
    else:
        for field_errors in form.errors.values():
            for error in field_errors:
                messages.error(request, error)
    return redirect("defenses:detail", pk=defense_request.pk)


@login_required
@require_POST
def comment_create(request, pk):
    """在「安排中」的申请下发表评论。"""
    defense_request = get_object_or_404(selectors.request_detail_queryset(), pk=pk)
    require(
        request,
        permissions.can_comment(request.user, defense_request),
        "defenses.comment.create.denied",
        defense_id=defense_request.pk,
    )
    form = DefenseCommentForm(request.POST)
    if form.is_valid():
        try:
            comment = add_comment(
                defense_request=defense_request,
                body=form.cleaned_data["body"],
                actor=request.user,
                request=request,
            )
        except DefenseError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, _("评论已发表。"))
            return redirect(
                f"{reverse('defenses:detail', args=(defense_request.pk,))}"
                f"#comment-{comment.pk}"
            )
    else:
        for field_errors in form.errors.values():
            for error in field_errors:
                messages.error(request, error)
    return redirect("defenses:detail", pk=defense_request.pk)


@login_required
@require_POST
def request_close(request, pk):
    """申请人或管理员关闭申请；此后只读。"""
    defense_request = get_object_or_404(selectors.request_detail_queryset(), pk=pk)
    require(
        request,
        permissions.can_close_request(request.user, defense_request),
        "defenses.request.close.denied",
        defense_id=defense_request.pk,
    )
    try:
        close_request(
            defense_request=defense_request,
            actor=request.user,
            request=request,
        )
    except DefenseError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            _("该申请已确定，正文与讨论进入只读状态。"),
        )
    return redirect("defenses:detail", pk=defense_request.pk)
