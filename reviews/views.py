"""Member-facing review queue and verdict submission."""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from projects.permissions import is_project_reviewer

from .forms import ReviewForm
from .models import ReviewAssignment
from .services import ReviewError, complete_review


logger = logging.getLogger(__name__)


def _require_reviewer(request):
    if not is_project_reviewer(request.user):
        logger.warning(
            "reviews.permission.denied username=%s path=%s",
            request.user.get_username(),
            request.path,
            extra={"request_id": getattr(request, "request_id", "-")},
        )
        raise PermissionDenied


@login_required
def review_queue(request):
    _require_reviewer(request)
    assignments = (
        ReviewAssignment.objects.filter(reviewer=request.user)
        .select_related("submission__group", "submission__submitted_by")
        .order_by("-assigned_at", "-id")
    )
    pending = [item for item in assignments if item.status == ReviewAssignment.PENDING]
    completed = [item for item in assignments if item.status == ReviewAssignment.COMPLETED]
    logger.info(
        "reviews.queue.view pending=%s completed=%s reviewer=%s",
        len(pending),
        len(completed),
        request.user.get_username(),
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return render(
        request,
        "reviews/queue.html",
        {"pending": pending, "completed": completed},
    )


@login_required
@require_POST
def complete_assignment(request, pk):
    _require_reviewer(request)
    assignment = get_object_or_404(
        ReviewAssignment.objects.select_related("submission__group"),
        pk=pk,
    )
    if assignment.reviewer_id != request.user.pk:
        raise PermissionDenied

    form = ReviewForm(request.POST)
    if form.is_valid():
        try:
            complete_review(
                assignment=assignment,
                reviewer=request.user,
                decision=form.cleaned_data["decision"],
                comment=form.cleaned_data["comment"],
                request=request,
            )
        except ReviewError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "评审已提交，感谢你的评审意见。")
    else:
        messages.error(request, "请填写评审意见并选择评审决定。")
    return redirect("projects:group_detail", pk=assignment.submission.group_id)
