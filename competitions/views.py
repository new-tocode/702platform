"""Member-facing competition listing and project-group registration."""

from collections import defaultdict
import logging

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from projects.models import ProjectGroup
from projects.permissions import can_manage_group, manageable_group_ids

from core.audit import record_audit

from .forms import CompetitionRegistrationForm
from .models import Competition, CompetitionRegistration
from .permissions import is_competition_manager


logger = logging.getLogger(__name__)
User = get_user_model()


def _require_competition_manager(request):
    if not is_competition_manager(request.user):
        logger.warning(
            "competition.permission.denied username=%s path=%s",
            request.user.get_username(),
            request.path,
            extra={"request_id": getattr(request, "request_id", "-")},
        )
        raise PermissionDenied


def _member_group_map(form):
    """Map each selectable member to the group ids they belong to.

    The browser uses this to filter options by the chosen group; server-side
    form validation remains authoritative.
    """
    group_ids = list(form.available_groups.values_list("pk", flat=True))
    if not group_ids:
        return {}

    through_model = ProjectGroup.members.through
    memberships = through_model.objects.filter(
        projectgroup_id__in=group_ids,
    ).values_list("user_id", "projectgroup_id")
    mapping = defaultdict(set)
    for user_id, group_id in memberships:
        mapping[str(user_id)].add(str(group_id))

    member_ids = form.fields["members"].queryset.values_list("pk", flat=True)
    return {
        str(member_id): sorted(mapping.get(str(member_id), set()))
        for member_id in member_ids
    }


@login_required
def competition_list(request):
    competitions = Competition.objects.select_related("published_by").all()

    # Managers (contacts/administrators) also see the registrations they can
    # edit or withdraw, fetched once and grouped to avoid per-row queries.
    manageable_ids = manageable_group_ids(request.user)
    registrations = (
        CompetitionRegistration.objects.filter(group_id__in=manageable_ids)
        .select_related("group", "team_leader__profile")
        .order_by("group__name", "id")
    )
    by_competition = defaultdict(list)
    for registration in registrations:
        by_competition[registration.competition_id].append(registration)

    competition_rows = [
        {
            "competition": competition,
            "registrations": by_competition.get(competition.pk, []),
        }
        for competition in competitions
    ]
    logger.info(
        "competition.list.view count=%s username=%s",
        len(competition_rows),
        request.user.get_username(),
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return render(
        request,
        "competitions/list.html",
        {"competition_rows": competition_rows},
    )


def _save_registration(*, form, competition, request, instance=None):
    """Create or update a registration from a validated form."""
    group = form.cleaned_data["group"]
    members = form.cleaned_data["members"]
    team_leader = form.cleaned_data["team_leader"]
    with transaction.atomic():
        if instance is None:
            registration = CompetitionRegistration.objects.create(
                competition=competition,
                group=group,
                registered_by=request.user,
                team_leader=team_leader,
                remark=form.cleaned_data.get("remark", ""),
            )
        else:
            registration = instance
            registration.group = group
            registration.team_leader = team_leader
            registration.remark = form.cleaned_data.get("remark", "")
            registration.save(
                update_fields=["group", "team_leader", "remark", "updated_at"]
            )
        registration.members.set(members)
    return registration


@login_required
def competition_register(request, pk):
    _require_competition_manager(request)
    competition = get_object_or_404(
        Competition.objects.select_related("published_by"),
        pk=pk,
    )

    if not competition.is_registration_open:
        logger.warning(
            "competition.registration.rejected competition_id=%s username=%s reason=closed_or_expired",
            competition.pk,
            request.user.get_username(),
            extra={"request_id": getattr(request, "request_id", "-")},
        )
        messages.error(request, "该竞赛已关闭报名或已超过报名截止时间。")
        return redirect("competitions:list")

    form = CompetitionRegistrationForm(
        user=request.user,
        competition=competition,
        data=request.POST or None,
    )
    context = {
        "competition": competition,
        "form": form,
        "member_group_map": _member_group_map(form),
        "is_edit": False,
    }

    if request.method == "POST":
        if form.is_valid():
            try:
                registration = _save_registration(
                    form=form,
                    competition=competition,
                    request=request,
                )
            except IntegrityError:
                form.add_error("group", "该项目组已经登记过这场竞赛，不能重复报名。")
                logger.warning(
                    "competition.registration.failure competition_id=%s username=%s reason=duplicate",
                    competition.pk,
                    request.user.get_username(),
                    extra={"request_id": getattr(request, "request_id", "-")},
                )
            else:
                record_audit(
                    action="competitions.registration",
                    user=request.user,
                    target=registration,
                    detail={
                        "competition_id": competition.pk,
                        "group_id": registration.group_id,
                        "member_count": registration.members.count(),
                    },
                    request=request,
                )
                logger.info(
                    "competition.registration.success registration_id=%s competition_id=%s group_id=%s username=%s",
                    registration.pk,
                    competition.pk,
                    registration.group_id,
                    request.user.get_username(),
                    extra={"request_id": getattr(request, "request_id", "-")},
                )
                messages.success(request, "竞赛报名登记成功。")
                return redirect("competitions:list")
        else:
            logger.warning(
                "competition.registration.failure competition_id=%s username=%s errors=%s",
                competition.pk,
                request.user.get_username(),
                form.errors.as_json(),
                extra={"request_id": getattr(request, "request_id", "-")},
            )

    return render(request, "competitions/register.html", context)


@login_required
def competition_registration_edit(request, pk):
    registration = get_object_or_404(
        CompetitionRegistration.objects.select_related("competition", "group"),
        pk=pk,
    )
    if not can_manage_group(request.user, registration.group):
        logger.warning(
            "competition.registration.edit.denied username=%s registration_id=%s",
            request.user.get_username(),
            registration.pk,
            extra={"request_id": getattr(request, "request_id", "-")},
        )
        raise PermissionDenied

    competition = registration.competition
    if not competition.is_registration_open:
        messages.error(request, "该竞赛已关闭报名或已超过报名截止时间，无法修改。")
        return redirect("competitions:list")

    form = CompetitionRegistrationForm(
        user=request.user,
        competition=competition,
        instance=registration,
        data=request.POST or None,
    )
    context = {
        "competition": competition,
        "registration": registration,
        "form": form,
        "member_group_map": _member_group_map(form),
        "is_edit": True,
    }

    if request.method == "POST":
        if form.is_valid():
            try:
                _save_registration(
                    form=form,
                    competition=competition,
                    request=request,
                    instance=registration,
                )
            except IntegrityError:
                form.add_error("group", "该项目组已经登记过这场竞赛，不能重复报名。")
            else:
                record_audit(
                    action="competitions.registration.update",
                    user=request.user,
                    target=registration,
                    detail={
                        "competition_id": competition.pk,
                        "group_id": registration.group_id,
                    },
                    request=request,
                )
                messages.success(request, "报名信息已更新。")
                return redirect("competitions:list")

    return render(request, "competitions/register.html", context)


@login_required
@require_POST
def competition_registration_withdraw(request, pk):
    registration = get_object_or_404(
        CompetitionRegistration.objects.select_related("competition", "group"),
        pk=pk,
    )
    if not can_manage_group(request.user, registration.group):
        logger.warning(
            "competition.registration.withdraw.denied username=%s registration_id=%s",
            request.user.get_username(),
            registration.pk,
            extra={"request_id": getattr(request, "request_id", "-")},
        )
        raise PermissionDenied

    detail = {
        "competition_id": registration.competition_id,
        "group_id": registration.group_id,
    }
    registration.delete()
    record_audit(
        action="competitions.registration.withdraw",
        user=request.user,
        detail=detail,
        request=request,
    )
    messages.success(request, "已放弃该竞赛报名。")
    return redirect("competitions:list")
