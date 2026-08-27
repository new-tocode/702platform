"""Read-only member-facing project group views."""

import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .models import ProjectGroup


logger = logging.getLogger(__name__)


@login_required
def group_list(request):
    groups = ProjectGroup.objects.select_related(
        "leader__profile",
    ).prefetch_related("members__profile")
    logger.info(
        "project_group.list.view count=%s user=%s",
        groups.count(),
        request.user.get_username(),
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return render(request, "projects/group_list.html", {"groups": groups})
