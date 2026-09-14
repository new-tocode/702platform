"""Member-facing review queue, verdict submission, and annotated-file downloads."""

import logging
import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from projects.permissions import can_view_group, is_project_reviewer

from .forms import ReviewForm
from .models import ArchivedProposal, ReviewAssignment
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


def _require_group_visibility(request, group, what):
    if not can_view_group(request.user, group):
        logger.warning(
            "reviews.download.denied username=%s group_id=%s what=%s path=%s",
            request.user.get_username(),
            group.pk,
            what,
            request.path,
            extra={"request_id": getattr(request, "request_id", "-")},
        )
        raise PermissionDenied


def _annotated_filename(file_field, round_number):
    """Build a neutral download name that reveals nothing about the reviewer."""
    extension = os.path.splitext(file_field.name)[1].lower()
    return f"批注版项目书_R{round_number}{extension}"


@login_required
def review_queue(request):
    _require_reviewer(request)
    assignments = (
        ReviewAssignment.objects.filter(reviewer=request.user)
        .select_related("submission__group", "submission__submitted_by")
        .order_by("-assigned_at", "-id")
    )
    pending = [item for item in assignments if item.status == ReviewAssignment.PENDING]
    completed = [
        item for item in assignments if item.status == ReviewAssignment.COMPLETED
    ]
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

    form = ReviewForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            complete_review(
                assignment=assignment,
                reviewer=request.user,
                decision=form.cleaned_data["decision"],
                comment=form.cleaned_data["comment"],
                annotated_file=form.cleaned_data.get("annotated_file"),
                request=request,
            )
        except ReviewError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "评审已提交，感谢你的评审意见。")
    else:
        for field_errors in form.errors.values():
            for error in field_errors:
                messages.error(request, error)
    return redirect("projects:group_detail", pk=assignment.submission.group_id)


@login_required
def annotated_file_download(request, pk):
    """Serve one reviewer's annotated copy to whoever may view the group."""
    assignment = get_object_or_404(
        ReviewAssignment.objects.select_related("submission__group"),
        pk=pk,
    )
    _require_group_visibility(request, assignment.submission.group, "annotated")
    if not assignment.annotated_file:
        raise Http404("该评审任务没有批注版项目书。")
    logger.info(
        "reviews.annotated.download assignment_id=%s submission_id=%s user=%s",
        assignment.pk,
        assignment.submission_id,
        request.user.get_username(),
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    # Serve through this view rather than exposing the media URL: Nginx serves
    # /media/ straight from disk, which would bypass the permission check above.
    return FileResponse(
        assignment.annotated_file.open("rb"),
        as_attachment=True,
        filename=_annotated_filename(
            assignment.annotated_file, assignment.submission.round
        ),
    )


@login_required
def archived_proposal_download(request, pk):
    """Serve an archived annotated proposal to whoever may view the group."""
    archived = get_object_or_404(
        ArchivedProposal.objects.select_related("group", "submission"),
        pk=pk,
    )
    _require_group_visibility(request, archived.group, "archived")
    logger.info(
        "reviews.archive.download archive_id=%s group_id=%s user=%s",
        archived.pk,
        archived.group_id,
        request.user.get_username(),
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return FileResponse(
        archived.file.open("rb"),
        as_attachment=True,
        filename=_annotated_filename(archived.file, archived.submission.round),
    )
