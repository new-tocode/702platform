"""Admin read-only view of the platform audit trail."""

from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "action",
        "user",
        "target_type",
        "target_id",
        "request_id",
        "ip_address",
    )
    list_filter = ("action", "created_at", "target_type")
    search_fields = (
        "action",
        "target_type",
        "target_id",
        "request_id",
        "user__username",
        "user__profile__full_name",
    )
    list_select_related = ("user",)
    readonly_fields = (
        "user",
        "action",
        "target_type",
        "target_id",
        "detail",
        "request_id",
        "ip_address",
        "created_at",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at", "-id")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
