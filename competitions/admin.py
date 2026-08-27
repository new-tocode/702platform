"""Django Admin management for competitions and registrations."""

import logging

from django.contrib import admin

from .forms import CompetitionRegistrationAdminForm
from .models import Competition, CompetitionRegistration


logger = logging.getLogger(__name__)


@admin.register(Competition)
class CompetitionAdmin(admin.ModelAdmin):
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "title",
                    "description",
                    "deadline",
                    "team_size",
                    "is_open",
                ),
            },
        ),
        (
            "发布信息",
            {
                "fields": ("published_by", "published_at", "created_at", "updated_at"),
            },
        ),
    )
    readonly_fields = ("published_by", "published_at", "created_at", "updated_at")
    list_display = (
        "title",
        "is_open",
        "deadline",
        "registration_status",
        "published_by",
        "published_at",
    )
    list_filter = ("is_open", "deadline", "published_at")
    search_fields = ("title", "description", "team_size", "published_by__username")
    list_select_related = ("published_by",)
    date_hierarchy = "deadline"
    ordering = ("-is_open", "deadline", "-published_at", "-id")

    @admin.display(description="报名状态")
    def registration_status(self, obj):
        return "开放" if obj.is_registration_open else "已关闭/截止"

    def save_model(self, request, obj, form, change):
        if not change:
            obj.published_by = request.user
        super().save_model(request, obj, form, change)
        logger.info(
            "admin.competition.save operator=%s competition_id=%s title=%s open=%s deadline=%s created=%s",
            request.user.get_username(),
            obj.pk,
            obj.title,
            obj.is_open,
            obj.deadline.isoformat(),
            not change,
            extra={"request_id": getattr(request, "request_id", "-")},
        )


@admin.register(CompetitionRegistration)
class CompetitionRegistrationAdmin(admin.ModelAdmin):
    form = CompetitionRegistrationAdminForm
    list_display = ("competition", "group", "registered_by", "member_count", "created_at")
    list_filter = ("competition", "created_at")
    search_fields = (
        "competition__title",
        "group__name",
        "group__leader__username",
        "registered_by__username",
    )
    filter_horizontal = ("members",)
    list_select_related = ("competition", "group", "registered_by")
    readonly_fields = ("registered_by", "created_at", "updated_at")
    ordering = ("-created_at", "-id")

    @admin.display(description="参赛人数")
    def member_count(self, obj):
        return obj.members.count()

    def save_model(self, request, obj, form, change):
        if not change:
            obj.registered_by = request.user
        super().save_model(request, obj, form, change)
        logger.info(
            "admin.competition_registration.save operator=%s registration_id=%s competition_id=%s group_id=%s created=%s",
            request.user.get_username(),
            obj.pk,
            obj.competition_id,
            obj.group_id,
            not change,
            extra={"request_id": getattr(request, "request_id", "-")},
        )
