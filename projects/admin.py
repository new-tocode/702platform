"""Admin management for project groups."""

import logging

from django.contrib import admin

from core.admin import ReadOnlyAdminMixin
from core.audit import record_audit

from .models import (
    MAX_ADVISORS_PER_GROUP,
    GroupCreateRequest,
    GroupJoinRequest,
    ProjectAdvisor,
    ProjectContact,
    ProjectGroup,
)
from .services import sync_group_membership


logger = logging.getLogger(__name__)


class ProjectAdvisorInline(admin.TabularInline):
    """指导老师随项目组一起编辑。

    槽位选单里只有「第 1/2 位」「第 3 位」，加上 ``max_num`` 的封顶，
    后台无法为同一项目组排出第 4 位；重复选同一槽位会撞上模型的唯一约束。
    """

    model = ProjectAdvisor
    extra = 0
    max_num = MAX_ADVISORS_PER_GROUP
    fields = ("sort_order", "name")
    ordering = ("sort_order",)


@admin.register(ProjectGroup)
class ProjectGroupAdmin(admin.ModelAdmin):
    inlines = (ProjectAdvisorInline,)
    list_display = (
        "name",
        "leader",
        "college",
        "member_count",
        "created_at",
        "updated_at",
    )
    search_fields = (
        "name",
        "description",
        "college",
        "leader__username",
        "leader__profile__full_name",
        "members__username",
        "members__profile__full_name",
        "advisors__name",
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
        sync_group_membership(
            group=form.instance,
            created=not change,
            actor=request.user,
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
class ProjectContactAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
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


@admin.register(GroupCreateRequest)
class GroupCreateRequestAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    """Oversight list for project-group creation applications.

    Requests are decided from the member-facing project-group page (any one
    administrator settles it), so the backend keeps this list read-only.
    """

    list_display = (
        "name",
        "applicant",
        "college",
        "status",
        "created_at",
        "decided_by",
        "decided_at",
    )
    list_filter = ("status", "created_at")
    search_fields = (
        "name",
        "description",
        "college",
        "applicant__username",
        "applicant__profile__full_name",
    )
    list_select_related = ("applicant", "decided_by")
    readonly_fields = (
        "name",
        "description",
        "college",
        "advisor_1",
        "advisor_2",
        "advisor_3",
        "applicant",
        "status",
        "decided_by",
        "decided_at",
        "created_group",
        "created_at",
        "updated_at",
    )
    date_hierarchy = "created_at"


@admin.register(GroupJoinRequest)
class GroupJoinRequestAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
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
