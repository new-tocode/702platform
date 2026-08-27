"""Member-facing competition listing and project-group registration."""

from collections import defaultdict
import logging

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render

from projects.models import ProjectGroup

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


def _member_options(form):
    """Build browser filtering metadata while server-side form validation remains authoritative."""
    group_ids = list(form.available_groups.values_list("pk", flat=True))
    if not group_ids:
        return []

    through_model = ProjectGroup.members.through
    memberships = through_model.objects.filter(
        projectgroup_id__in=group_ids,
    ).values_list("user_id", "projectgroup_id")
    user_group_ids = defaultdict(list)
    for user_id, group_id in memberships:
        user_group_ids[user_id].append(str(group_id))

    return [
        (member, ",".join(user_group_ids[member.pk]))
        for member in form.fields["members"].queryset
    ]


@login_required
def competition_list(request):
    _require_competition_manager(request)
    competitions = Competition.objects.select_related("published_by").all()
    logger.info(
        "competition.list.view count=%s username=%s",
        competitions.count(),
        request.user.get_username(),
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return render(
        request,
        "competitions/list.html",
        {"competitions": competitions},
    )


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
        "member_options": _member_options(form),
    }

    if request.method == "POST":
        if form.is_valid():
            group = form.cleaned_data["group"]
            members = form.cleaned_data["members"]
            try:
                with transaction.atomic():
                    registration = CompetitionRegistration.objects.create(
                        competition=competition,
                        group=group,
                        registered_by=request.user,
                        remark=form.cleaned_data.get("remark", ""),
                    )
                    registration.members.set(members)
            except IntegrityError:
                form.add_error("group", "该项目组已经登记过这场竞赛，不能重复报名。")
                logger.warning(
                    "competition.registration.failure competition_id=%s group_id=%s username=%s reason=duplicate",
                    competition.pk,
                    group.pk,
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
                        "group_id": group.pk,
                        "member_count": members.count(),
                    },
                    request=request,
                )
                logger.info(
                    "competition.registration.success registration_id=%s competition_id=%s group_id=%s member_count=%s username=%s",
                    registration.pk,
                    competition.pk,
                    group.pk,
                    members.count(),
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
