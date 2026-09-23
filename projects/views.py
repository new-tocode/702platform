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
from django.utils.translation import gettext as _, ngettext
from django.views.decorators.http import require_POST

from core.audit import record_audit
from core.permissions import is_admin, require

from .forms import (
    ContactTransferForm,
    GroupCreateRequestForm,
    GroupDescriptionForm,
    GroupInfoForm,
    GroupJoinRequestForm,
    GroupProposalForm,
)
from .models import GroupCreateRequest, GroupJoinRequest, ProjectGroup
from .permissions import (
    can_decide_group_create_requests,
    can_manage_group,
    can_view_group,
    groups_visible_to,
    manageable_group_ids,
    member_group_ids,
)
from .services import (
    GroupCreateRequestError,
    GroupManagementError,
    JoinRequestError,
    apply_to_create_group,
    apply_to_group,
    approve_create_request,
    approve_join_request,
    reject_create_request,
    reject_join_request,
    remove_group_member,
    transfer_contact,
    update_group_description,
    update_group_info,
)


logger = logging.getLogger(__name__)
User = get_user_model()


def _require_group_manager(request, group):
    require(
        request,
        can_manage_group(request.user, group),
        "project_group.permission.denied",
        group_id=group.pk,
    )


def _submit_message(submission):
    """送审成功的回执。名额可能只有 1 名（大创立项），所以按单复数取句子。"""
    required = submission.required_reviewers
    return ngettext(
        "已提交第 %(round)s 轮评审（%(type)s），"
        "等待初审人初审；初审通过后将随机分配 1 名评审人。",
        "已提交第 %(round)s 轮评审（%(type)s），"
        "等待初审人初审；初审通过后将随机分配 %(count)s 名评审人。",
        required,
    ) % {
        "round": submission.round,
        "type": submission.get_review_type_display(),
        "count": required,
    }


@login_required
def group_list(request):
    from reviews.models import ProjectSubmission

    groups = (
        groups_visible_to(request.user)
        .select_related("leader__profile")
        .prefetch_related("members__profile")
        .prefetch_related("advisors")
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
                "can_view": is_admin(request.user) or group.pk in member_ids,
                "status_label": latest.get_status_display() if latest else "",
                # 语气色由模型给（见 reviews.lifecycle.STATUS_TONES），模板不再比状态字符串。
                "status_tone": latest.status_tone if latest else "",
            }
        )
    # 申请人自己看得到那条待审申请的状态；审核入口在管理员的「评审」页，
    # 不在这一页（见 reviews.panels.pending_create_requests）。
    my_create_request = GroupCreateRequest.objects.filter(
        applicant=request.user,
        status=GroupCreateRequest.PENDING,
    ).first()
    logger.info(
        "project_group.list.view count=%s user=%s",
        len(group_rows),
        request.user.get_username(),
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return render(
        request,
        "projects/group_list.html",
        {"group_rows": group_rows, "my_create_request": my_create_request},
    )


@login_required
def group_detail(request, pk):
    # 局部导入：让 projects 不在模块加载期就依赖 reviews。
    from reviews.panels import group_detail_context

    group = get_object_or_404(
        ProjectGroup.objects.select_related("leader__profile").prefetch_related(
            "members__profile", "advisors"
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
        .prefetch_related("tasks__reviewer__profile")
        .order_by("-round", "-id")
    )
    context = {
        "group": group,
        "submissions": submissions,
        "latest_submission": submissions[0] if submissions else None,
        "archived_proposals": group.archived_proposals.select_related("submission"),
        "can_manage": can_manage_group(request.user, group),
    }
    # 评审那一半（我的任务、可行使的超级评审、三个表单）由评审应用自己装配。
    context.update(
        group_detail_context(submissions=submissions, user=request.user)
    )
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
        messages.success(request, _("项目书已上传/更新。"))
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
            _submit_message(submission),
        )
    return redirect("projects:group_detail", pk=group.pk)


@login_required
def group_proposal_download(request, pk):
    group = get_object_or_404(ProjectGroup, pk=pk)
    if not can_view_group(request.user, group):
        raise PermissionDenied
    if not group.proposal:
        raise Http404(_("该项目组尚未上传项目书。"))
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
        messages.info(request, _("你已经是该项目组成员。"))
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
                _("已提交加入「%(name)s」的申请，请等待联系人审核。") % {"name": group.name},
            )
        return redirect("projects:group_list")

    return render(
        request,
        "projects/group_apply.html",
        {"group": group, "form": form},
    )


@login_required
def group_create_request(request):
    """Any logged-in member — whatever their role — may apply to found a group."""
    pending_request = GroupCreateRequest.objects.filter(
        applicant=request.user,
        status=GroupCreateRequest.PENDING,
    ).first()
    # 已有一条待审申请时用它的内容作初值：再进来是改，不是从头再填一遍。
    form = GroupCreateRequestForm(request.POST or None, instance=pending_request)
    if request.method == "POST" and form.is_valid():
        try:
            apply_to_create_group(
                applicant=request.user,
                name=form.cleaned_data["name"],
                description=form.cleaned_data["description"],
                college=form.cleaned_data["college"],
                advisor_names=form.advisor_names(),
                request=request,
            )
        except GroupCreateRequestError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(
                request,
                _("已提交创建项目组的申请，等待管理员审核；任一管理员同意后项目组即刻建立，你成为项目组联系人。"),
            )
        return redirect("projects:group_list")
    return render(
        request,
        "projects/group_create_request.html",
        {"form": form, "pending_request": pending_request},
    )


@login_required
@require_POST
def group_create_decide(request, req_pk, action):
    """Settle a creation request; the first administrator to act decides it."""
    if not can_decide_group_create_requests(request.user):
        logger.warning(
            "project_group.create.decide.denied username=%s create_request_id=%s",
            request.user.get_username(),
            req_pk,
            extra={"request_id": getattr(request, "request_id", "-")},
        )
        raise PermissionDenied
    create_request = get_object_or_404(GroupCreateRequest, pk=req_pk)
    try:
        if action == "approve":
            approved = approve_create_request(
                create_request=create_request,
                actor=request.user,
                request=request,
            )
            messages.success(
                request,
                _("已通过创建申请，项目组「%(name)s」已建立并出现在项目组列表中。")
                % {"name": approved.name},
            )
        elif action == "reject":
            rejected = reject_create_request(
                create_request=create_request,
                actor=request.user,
                request=request,
            )
            messages.success(request, _("已拒绝创建「%(name)s」的申请。") % {"name": rejected.name})
        else:
            raise Http404(_("未知操作"))
    except GroupCreateRequestError as exc:
        messages.error(request, str(exc))
    # 处理入口在「评审」页，处理完回到那里继续看待办。
    return redirect("reviews:queue")


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
    info_form = GroupInfoForm(instance=group)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "info":
            info_form = GroupInfoForm(request.POST, instance=group)
            if info_form.is_valid():
                update_group_info(
                    group=group,
                    college=info_form.cleaned_data["college"],
                    advisor_names=info_form.advisor_names(),
                    actor=request.user,
                    request=request,
                )
                messages.success(request, _("学院与指导老师已更新。"))
                return redirect("projects:group_manage", pk=group.pk)
        elif action == "description":
            description_form = GroupDescriptionForm(request.POST, instance=group)
            if description_form.is_valid():
                update_group_description(
                    group=group,
                    description=description_form.cleaned_data["description"],
                    actor=request.user,
                    request=request,
                )
                messages.success(request, _("项目组介绍已更新。"))
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
                messages.success(request, _("已转让项目组联系人。"))
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
            "info_form": info_form,
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
            messages.success(request, _("已通过该入组申请。"))
        elif action == "reject":
            reject_join_request(
                join_request=join_request,
                actor=request.user,
                request=request,
            )
            messages.success(request, _("已拒绝该入组申请。"))
        else:
            raise Http404(_("未知操作"))
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
        messages.success(request, _("已将 %(name)s 移出项目组。") % {"name": member.get_username()})
    except GroupManagementError as exc:
        messages.error(request, str(exc))
    return redirect("projects:group_manage", pk=group.pk)
