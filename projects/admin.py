"""Admin management for project groups."""

import logging

from django.contrib import admin

from core.audit import record_audit

from .models import GroupJoinRequest, ProjectContact, ProjectGroup


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
        record_audit(
            action=(
                "projects.group.membership.create"
                if not change
                else "projects.group.membership.update"
            ),
            user=request.user,
            target=form.instance,
            detail={
                "leader_id": form.instance.leader_id,
                "member_ids": list(form.instance.members.values_list("pk", flat=True)),
            },
            request=request,
        )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        record_audit(
            action="projects.group.create" if not change else "projects.group.update",
            user=request.user,
            target=obj,
            detail={"leader_id": obj.leader_id},
            request=request,
        )
        logger.info(
            "admin.project_group.save operator=%s group_id=%s name=%s leader_id=%s created=%s",
            request.user.get_username(),
            obj.pk,
            obj.name,
            obj.leader_id,
            not change,
            extra={"request_id": getattr(request, "request_id", "-")},
        )


@admin.register(ProjectContact)
class ProjectContactAdmin(admin.ModelAdmin):
    """Read-only list of every project-group contact at a glance."""

    list_display = (
        "username",
        "profile_name",
        "contact_groups",
        "is_active",
        "is_staff",
    )
    search_fields = ("username", "profile__full_name", "led_project_groups__name")
    ordering = ("username",)
    list_select_related = ("profile",)

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .filter(led_project_groups__isnull=False)
            .distinct()
            .select_related("profile")
            .prefetch_related("led_project_groups")
        )

    @admin.display(description="姓名", ordering="profile__full_name")
    def profile_name(self, obj):
        return obj.profile.full_name

    @admin.display(description="负责的项目组")
    def contact_groups(self, obj):
        names = [group.name for group in obj.led_project_groups.all()]
        return "、".join(names) or "—"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(GroupJoinRequest)
class GroupJoinRequestAdmin(admin.ModelAdmin):
    """Oversight list for membership applications reviewed by contacts."""

    list_display = ("group", "applicant", "status", "created_at", "decided_by", "decided_at")
    list_filter = ("status", "created_at")
    search_fields = ("group__name", "applicant__username", "applicant__profile__full_name")
    list_select_related = ("group", "applicant", "decided_by")
    readonly_fields = (
        "group",
        "applicant",
        "message",
        "status",
        "decided_by",
        "decided_at",
        "created_at",
        "updated_at",
    )
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
