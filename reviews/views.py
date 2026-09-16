"""Member-facing review queue, verdict submission, and annotated-file downloads."""

import logging
import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from projects.permissions import (
    can_view_group,
    is_preliminary_reviewer,
    is_project_reviewer,
    is_super_reviewer,
)

from .forms import PreliminaryReviewForm, ReviewForm, ReviewerLeaveForm
from .models import (
    ArchivedProposal,
    PreliminaryReview,
    ProjectSubmission,
    ReviewAssignment,
)
from .services import (
    ReviewError,
    clear_reviewer_leave,
    complete_preliminary_review,
    complete_review,
    override_blocker,
    override_review,
    set_reviewer_leave,
)


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


def _require_preliminary_reviewer(request):
    if not is_preliminary_reviewer(request.user):
        logger.warning(
            "reviews.permission.denied username=%s path=%s reason=no_preliminary_qualification",
            request.user.get_username(),
            request.path,
            extra={"request_id": getattr(request, "request_id", "-")},
        )
        raise PermissionDenied


def _require_super_reviewer(request):
    if not is_super_reviewer(request.user):
        logger.warning(
            "reviews.permission.denied username=%s path=%s reason=not_super_reviewer",
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
    context = {
        "show_preliminary": is_preliminary_reviewer(request.user),
        # 超级评审没有自己的队列任务，但整页都归他们看，所以也算「评审」这一侧。
        "show_review": bool(
            getattr(request.user, "is_reviewer", False)
            or is_super_reviewer(request.user)
        ),
    }
    if context["show_preliminary"]:
        # 初审任务与评审任务是两件事：同一个人可能两种都持有，各自排队。
        preliminary = (
            PreliminaryReview.objects.filter(reviewer=request.user)
            .select_related("submission__group", "submission__submitted_by")
            .order_by("-assigned_at", "-id")
        )
        context["preliminary_pending"] = [
            item for item in preliminary if item.status == PreliminaryReview.PENDING
        ]
        context["preliminary_completed"] = [
            item for item in preliminary if item.status == PreliminaryReview.COMPLETED
        ]
        # 被超级评审释放的那一条也要列出来：否则初审人只会看到任务凭空消失。
        context["preliminary_released"] = [
            item for item in preliminary if item.status == PreliminaryReview.RELEASED
        ]
    if context["show_review"]:
        assignments = (
            ReviewAssignment.objects.filter(reviewer=request.user)
            .select_related("submission__group", "submission__submitted_by")
            .order_by("-assigned_at", "-id")
        )
        context["pending"] = [
            item for item in assignments if item.status == ReviewAssignment.PENDING
        ]
        context["completed"] = [
            item for item in assignments if item.status == ReviewAssignment.COMPLETED
        ]
        context["released"] = [
            item for item in assignments if item.status == ReviewAssignment.RELEASED
        ]
    if is_super_reviewer(request.user):
        # The super reviewer's reach: every round still in progress, whether or
        # not they hold a task on it — a round waiting on its 初审 is in progress
        # too, and being able to settle it is the point of the role. Rounds they
        # cannot act on stay listed — seeing the whole picture is the point — but
        # each says why.
        context["open_rounds"] = [
            {
                "submission": submission,
                "blocker": override_blocker(submission=submission, user=request.user),
            }
            for submission in ProjectSubmission.objects.filter(
                status__in=ProjectSubmission.OPEN_STATUSES
            )
            .select_related("group", "submitted_by")
            .order_by("submitted_at", "id")
        ]
    logger.info(
        "reviews.queue.view preliminary_pending=%s preliminary_released=%s pending=%s completed=%s released=%s super=%s reviewer=%s",
        len(context.get("preliminary_pending", ())),
        len(context.get("preliminary_released", ())),
        len(context.get("pending", ())),
        len(context.get("completed", ())),
        len(context.get("released", ())),
        is_super_reviewer(request.user),
        request.user.get_username(),
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return render(request, "reviews/queue.html", context)


@login_required
@require_POST
def override_submission(request, pk):
    """Let a super reviewer settle an in-progress round with a single vote."""
    _require_super_reviewer(request)
    submission = get_object_or_404(
        ProjectSubmission.objects.select_related("group"),
        pk=pk,
    )
    form = ReviewForm(request.POST, request.FILES, prefix="override")
    if form.is_valid():
        try:
            decided = override_review(
                submission=submission,
                super_reviewer=request.user,
                decision=form.cleaned_data["decision"],
                comment=form.cleaned_data["comment"],
                annotated_file=form.cleaned_data.get("annotated_file"),
                request=request,
            )
        except ReviewError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(
                request,
                f"超级评审已敲定第 {decided.round} 轮：{decided.get_status_display()}，"
                "等待中的任务（含初审）已释放。",
            )
    else:
        for field_errors in form.errors.values():
            for error in field_errors:
                messages.error(request, error)
    return redirect("projects:group_detail", pk=submission.group_id)


@login_required
@require_POST
def complete_preliminary(request, pk):
    """Record the 初审 verdict; a 通过 hands the round to its reviewers."""
    _require_preliminary_reviewer(request)
    preliminary = get_object_or_404(
        PreliminaryReview.objects.select_related("submission__group"),
        pk=pk,
    )
    if preliminary.reviewer_id != request.user.pk:
        raise PermissionDenied

    form = PreliminaryReviewForm(request.POST)
    if form.is_valid():
        decision = form.cleaned_data["decision"]
        try:
            reviewed = complete_preliminary_review(
                preliminary=preliminary,
                reviewer=request.user,
                decision=decision,
                comment=form.cleaned_data["comment"],
                request=request,
            )
        except ReviewError as exc:
            messages.error(request, str(exc))
        else:
            if decision == PreliminaryReview.APPROVE:
                messages.success(
                    request,
                    "初审已通过，已随机分配 "
                    f"{reviewed.submission.required_reviewers} 名评审人。",
                )
            else:
                messages.success(
                    request,
                    "初审已打回，项目组修改项目书后可重新提交。",
                )
    else:
        for field_errors in form.errors.values():
            for error in field_errors:
                messages.error(request, error)
    return redirect("projects:group_detail", pk=preliminary.submission.group_id)


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
@require_POST
def set_leave(request):
    """Register or adjust the reviewer's own review-leave window."""
    _require_reviewer(request)
    form = ReviewerLeaveForm(request.POST)
    if form.is_valid():
        try:
            leave = set_reviewer_leave(
                reviewer=request.user,
                starts_at=form.cleaned_data["starts_at"],
                ends_at=form.cleaned_data["ends_at"],
                reason=form.cleaned_data["reason"],
                actor=request.user,
                request=request,
            )
        except ReviewError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(
                request,
                f"已登记评审请假：{leave.starts_at:%Y-%m-%d %H:%M} 至 "
                f"{leave.ends_at:%Y-%m-%d %H:%M}，期间不再接收新的评审请求。",
            )
    else:
        for field_errors in form.errors.values():
            for error in field_errors:
                messages.error(request, error)
    return redirect("accounts:member_home")


@login_required
@require_POST
def cancel_leave(request):
    """Drop the reviewer's own open leave window."""
    _require_reviewer(request)
    try:
        clear_reviewer_leave(
            reviewer=request.user,
            actor=request.user,
            request=request,
        )
    except ReviewError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "已取消请假，即刻恢复接收评审请求。")
    return redirect("accounts:member_home")


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
