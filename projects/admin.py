"""Admin management for project groups."""

import logging

from django.contrib import admin

from .models import ProjectGroup


logger = logging.getLogger(__name__)


@admin.register(ProjectGroup)
class ProjectGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "leader", "member_count", "created_at", "updated_at")
    search_fields = (
        "name",
        "description",
        "leader__username",
        "leader__profile__full_name",
        "members__username",
        "members__profile__full_name",
    )
    list_filter = ("created_at", "updated_at")
    filter_horizontal = ("members",)
    list_select_related = ("leader",)
    readonly_fields = ("created_at", "updated_at")
    ordering = ("name", "id")

    @admin.display(description="成员数")
    def member_count(self, obj):
        return obj.members.count()

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        if form.instance.leader_id:
            form.instance.members.add(form.instance.leader_id)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        if form.instance.leader_id:
            form.instance.members.add(form.instance.leader_id)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        logger.info(
            "admin.project_group.save operator=%s group_id=%s name=%s leader_id=%s created=%s",
            request.user.get_username(),
            obj.pk,
            obj.name,
            obj.leader_id,
            not change,
            extra={"request_id": getattr(request, "request_id", "-")},
        )
