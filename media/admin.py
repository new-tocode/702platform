"""Django Admin configuration for the shared media library."""

import logging

from django.contrib import admin

from core.audit import record_audit

from .models import MediaFile


logger = logging.getLogger(__name__)


@admin.register(MediaFile)
class MediaFileAdmin(admin.ModelAdmin):
    fieldsets = (
        (
            None,
            {
                "fields": ("file", "kind", "caption"),
            },
        ),
        (
            "上传信息",
            {
                "fields": ("uploader", "file_size", "created_at"),
            },
        ),
    )
    readonly_fields = ("uploader", "file_size", "created_at")
    list_display = (
        "filename_display",
        "kind",
        "caption",
        "size_display",
        "uploader",
        "created_at",
    )
    list_filter = ("kind", "created_at")
    search_fields = (
        "file",
        "caption",
        "uploader__username",
        "uploader__profile__full_name",
    )
    list_select_related = ("uploader",)
    date_hierarchy = "created_at"
    ordering = ("-created_at", "-id")

    @admin.display(description="文件", ordering="file")
    def filename_display(self, obj):
        return obj.filename

    @admin.display(description="大小", ordering="file_size")
    def size_display(self, obj):
        return f"{obj.size_in_mb} MB"

    def save_model(self, request, obj, form, change):
        if not change:
            obj.uploader = request.user
        super().save_model(request, obj, form, change)
        record_audit(
            action="media.create" if not change else "media.update",
            user=request.user,
            target=obj,
            detail={"kind": obj.kind, "file_size": obj.file_size},
            request=request,
        )
        logger.info(
            "admin.media.save operator=%s media_id=%s filename=%s kind=%s size=%s created=%s",
            request.user.get_username(),
            obj.pk,
            obj.filename,
            obj.kind,
            obj.file_size,
            not change,
            extra={"request_id": getattr(request, "request_id", "-")},
        )
