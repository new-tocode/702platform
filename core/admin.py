"""Admin read-only view of the platform audit trail."""

from django.contrib import admin

from .models import AuditLog


class ReadOnlyAdminMixin:
    """后台只读：看得到、搜得到，加不出来也改不了。

    留痕类的记录（审计日志、各类申请、归档、名册）都只该被查看，这层把
    「不能新增、不能修改」收成一处。**不覆写 has_delete_permission**——
    各模型的删除口径本就不同（审计日志明确关掉，其余交给 Django 权限），
    一并改掉会动到既有行为。
    """

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(AuditLog)
class AuditLogAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
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

    def has_delete_permission(self, request, obj=None):
        # 审计留痕连删除也不给——只读记录里唯一一条明确禁删的。
        return False
