"""Django Admin configuration for administrator-published notices."""

import logging

from django.contrib import admin

from core.audit import record_audit

from .forms import NoticeAdminForm
from .models import Notice


logger = logging.getLogger(__name__)


@admin.register(Notice)
class NoticeAdmin(admin.ModelAdmin):
    form = NoticeAdminForm
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "title",
                    "content",
                    "scope",
                    "visible_groups",
                    "attachments",
                    "is_pinned",
                ),
            },
        ),
        (
            "发布信息",
            {
                "fields": (
                    "published_by",
                    "published_at",
                    "updated_at",
                ),
            },
        ),
    )
    readonly_fields = ("published_by", "published_at", "updated_at")
    list_display = (
        "title",
        "scope",
        "is_pinned",
        "visible_groups_display",
        "published_by",
        "published_at",
        "updated_at",
    )
    list_filter = ("scope", "is_pinned", "published_at")
    search_fields = ("title", "content", "published_by__username", "published_by__profile__full_name")
    list_select_related = ("published_by",)
    date_hierarchy = "published_at"
    ordering = ("-is_pinned", "-published_at", "-id")

    @admin.display(description="可查看用户组")
    def visible_groups_display(self, obj):
        if obj.scope == Notice.CONTACTS:
            return "全部项目组联系人"
        return ", ".join(obj.visible_groups.values_list("name", flat=True)) or "—"

    def save_model(self, request, obj, form, change):
        if not change:
            obj.published_by = request.user
        super().save_model(request, obj, form, change)
        record_audit(
            action="notices.create" if not change else "notices.update",
            user=request.user,
            target=obj,
            detail={"scope": obj.scope, "is_pinned": obj.is_pinned},
            request=request,
        )
        logger.info(
            "admin.notice.save operator=%s notice_id=%s title=%s scope=%s pinned=%s created=%s",
            request.user.get_username(),
            obj.pk,
            obj.title,
            obj.scope,
            obj.is_pinned,
            not change,
            extra={"request_id": getattr(request, "request_id", "-")},
        )
