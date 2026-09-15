"""Member-facing project group views: browse, detail, apply, and manage."""

import logging
import os

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Prefetch
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.audit import record_audit

from .forms import (
    ContactTransferForm,
    GroupDescriptionForm,
    GroupJoinRequestForm,
    GroupProposalForm,
)
from .models import GroupJoinRequest, ProjectGroup
from .permissions import (
    can_manage_group,
    can_view_group,
    groups_visible_to,
    is_super_reviewer,
    manageable_group_ids,
    member_group_ids,
)
from .services import (
    GroupManagementError,
    JoinRequestError,
    apply_to_group,
    approve_join_request,
    reject_join_request,
    remove_group_member,
    transfer_contact,
    update_group_description,
)


logger = logging.getLogger(__name__)
User = get_user_model()


def _require_group_manager(request, group):
    if not can_manage_group(request.user, group):
        logger.warning(
            "project_group.permission.denied username=%s group_id=%s path=%s",
            request.user.get_username(),
            group.pk,
            request.path,
            extra={"request_id": getattr(request, "request_id", "-")},
        )
        raise PermissionDenied


@login_required
def group_list(request):
    from reviews.models import ProjectSubmission

    groups = (
        groups_visible_to(request.user)
        .select_related("leader__profile")
        .prefetch_related("members__profile")
        .prefetch_related(
            Prefetch(
                "submissions",
                queryset=ProjectSubmission.objects.order_by("-round", "-id"),
                to_attr="ordered_submissions",
            )
        )
        .annotate(member_count=Count("members", distinct=True))
        .order_by("name", "id")
    )
    manageable_ids = set(manageable_group_ids(request.user))
    member_ids = set(member_group_ids(request.user))
    pending_ids = set(
        GroupJoinRequest.objects.filter(
            applicant=request.user,
            status=GroupJoinRequest.PENDING,
        ).values_list("group_id", flat=True)
    )
    group_rows = []
    for group in groups:
        latest = group.ordered_submissions[0] if group.ordered_submissions else None
        group_rows.append(
            {
                "group": group,
                "can_manage": group.pk in manageable_ids,
                "is_member": group.pk in member_ids,
                "has_pending": group.pk in pending_ids,
                "can_view": request.user.is_staff or group.pk in member_ids,
                "status_label": latest.get_status_display() if latest else "",
                "status": latest.status if latest else "",
            }
        )
    logger.info(
        "project_group.list.view count=%s user=%s",
        len(group_rows),
        request.user.get_username(),
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return render(request, "projects/group_list.html", {"group_rows": group_rows})


@login_required
def group_detail(request, pk):
    from reviews.forms import ReviewForm
    from reviews.models import ReviewAssignment
    from reviews.services import can_override_review

    group = get_object_or_404(
        ProjectGroup.objects.select_related("leader__profile").prefetch_related(
            "members__profile"
        ),
        pk=pk,
    )
    if not can_view_group(request.user, group):
        logger.warning(
            "project_group.detail.denied username=%s group_id=%s",
            request.user.get_username(),
            group.pk,
            extra={"request_id": getattr(request, "request_id", "-")},
        )
        raise PermissionDenied

    submissions = list(
        group.submissions.select_related("submitted_by__profile")
        .prefetch_related("assignments__reviewer__profile")
        .order_by("-round", "-id")
    )
    latest = submissions[0] if submissions else None
    my_assignment = None
    if latest is not None and getattr(request.user, "is_reviewer", False):
        my_assignment = next(
            (
                assignment
                for assignment in latest.assignments.all()
                if assignment.reviewer_id == request.user.pk
                and assignment.status == ReviewAssignment.PENDING
            ),
            None,
        )
    can_override = latest is not None and can_override_review(
        submission=latest,
        user=request.user,
    )
    context = {
        "group": group,
        "submissions": submissions,
        "latest_submission": latest,
        "my_assignment": my_assignment,
        "review_form": ReviewForm(),
        "archived_proposals": group.archived_proposals.select_related("submission"),
        "can_override": can_override,
        "can_manage": can_manage_group(request.user, group),
    }
    if can_override:
        # Prefixed so its field ids cannot clash with the reviewer form above.
        context["override_form"] = ReviewForm(prefix="override")
    return render(request, "projects/group_detail.html", context)


@login_required
@require_POST
def group_proposal_update(request, pk):
    group = get_object_or_404(ProjectGroup, pk=pk)
    _require_group_manager(request, group)

    form = GroupProposalForm(request.POST, request.FILES, instance=group)
    if form.is_valid():
        form.save()
        record_audit(
            action="projects.group.proposal.update",
            user=request.user,
            target=group,
            detail={},
            request=request,
        )
        messages.success(request, "项目书已上传/更新。")
    else:
        for error in form.errors.get("proposal", []):
            messages.error(request, error)
    return redirect("projects:group_manage", pk=group.pk)


@login_required
@require_POST
def group_submit_review(request, pk):
    from reviews.forms import SubmissionForm
    from reviews.services import ReviewError, submit_for_review

    group = get_object_or_404(ProjectGroup, pk=pk)
    _require_group_manager(request, group)

    form = SubmissionForm(request.POST)
    if not form.is_valid():
        for field_errors in form.errors.values():
            for error in field_errors:
                messages.error(request, error)
        return redirect("projects:group_detail", pk=group.pk)

    try:
        submission = submit_for_review(
            group=group,
            submitter=request.user,
            review_type=form.cleaned_data["review_type"],
            message=form.cleaned_data["message"],
            request=request,
        )
    except ReviewError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            f"已提交第 {submission.round} 轮评审"
            f"（{submission.get_review_type_display()}，需 {submission.required_reviewers} 名评审人），"
            "等待评审人返回意见。",
        )
    return redirect("projects:group_detail", pk=group.pk)


@login_required
def group_proposal_download(request, pk):
    group = get_object_or_404(ProjectGroup, pk=pk)
    if not can_view_group(request.user, group):
        raise PermissionDenied
    if not group.proposal:
        raise Http404("该项目组尚未上传项目书。")
    return FileResponse(
        group.proposal.open("rb"),
        as_attachment=True,
        filename=os.path.basename(group.proposal.name),
    )


@login_required
def group_apply(request, pk):
    group = get_object_or_404(
        ProjectGroup.objects.select_related("leader__profile"),
        pk=pk,
    )
    if group.members.filter(pk=request.user.pk).exists():
        messages.info(request, "你已经是该项目组成员。")
        return redirect("projects:group_list")

    form = GroupJoinRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            apply_to_group(
                group=group,
                applicant=request.user,
                message=form.cleaned_data.get("message", ""),
                request=request,
            )
        except JoinRequestError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(
                request,
                f"已提交加入「{group.name}」的申请，请等待联系人审核。",
            )
        return redirect("projects:group_list")

    return render(
        request,
        "projects/group_apply.html",
        {"group": group, "form": form},
    )


@login_required
def group_manage(request, pk):
    from reviews.forms import SubmissionForm

    group = get_object_or_404(
        ProjectGroup.objects.select_related("leader__profile"),
        pk=pk,
    )
    _require_group_manager(request, group)

    description_form = GroupDescriptionForm(instance=group)
    transfer_form = ContactTransferForm(group)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "description":
            description_form = GroupDescriptionForm(request.POST, instance=group)
            if description_form.is_valid():
                update_group_description(
                    group=group,
                    description=description_form.cleaned_data["description"],
                    actor=request.user,
                    request=request,
                )
                messages.success(request, "项目组介绍已更新。")
                return redirect("projects:group_manage", pk=group.pk)
        elif action == "transfer":
            transfer_form = ContactTransferForm(group, request.POST)
            if transfer_form.is_valid():
                transfer_contact(
                    group=group,
                    new_contact=transfer_form.cleaned_data["new_contact"],
                    actor=request.user,
                    request=request,
                )
                messages.success(request, "已转让项目组联系人。")
                return redirect("projects:group_manage", pk=group.pk)

    join_requests = (
        group.join_requests.filter(status=GroupJoinRequest.PENDING)
        .select_related("applicant__profile")
        .order_by("created_at", "id")
    )
    members = group.members.select_related("profile").order_by("username")
    latest_submission = (
        group.submissions.select_related("submitted_by").order_by("-round", "-id").first()
    )
    return render(
        request,
        "projects/group_manage.html",
        {
            "group": group,
            "members": members,
            "join_requests": join_requests,
            "description_form": description_form,
            "transfer_form": transfer_form,
            "proposal_form": GroupProposalForm(instance=group),
            "submit_form": SubmissionForm(),
            "latest_submission": latest_submission,
        },
    )


@login_required
@require_POST
def group_request_decide(request, pk, req_pk, action):
    group = get_object_or_404(ProjectGroup, pk=pk)
    _require_group_manager(request, group)
    join_request = get_object_or_404(GroupJoinRequest, pk=req_pk, group=group)

    try:
        if action == "approve":
            approve_join_request(
                join_request=join_request,
                actor=request.user,
                request=request,
            )
            messages.success(request, "已通过该入组申请。")
        elif action == "reject":
            reject_join_request(
                join_request=join_request,
                actor=request.user,
                request=request,
            )
            messages.success(request, "已拒绝该入组申请。")
        else:
            raise Http404("未知操作")
    except JoinRequestError as exc:
        messages.error(request, str(exc))
    return redirect("projects:group_manage", pk=group.pk)


@login_required
@require_POST
def group_member_remove(request, pk, user_pk):
    group = get_object_or_404(ProjectGroup, pk=pk)
    _require_group_manager(request, group)
    member = get_object_or_404(User, pk=user_pk)

    try:
        remove_group_member(
            group=group,
            member=member,
            actor=request.user,
            request=request,
        )
        messages.success(request, f"已将 {member.get_username()} 移出项目组。")
    except GroupManagementError as exc:
        messages.error(request, str(exc))
    return redirect("projects:group_manage", pk=group.pk)
