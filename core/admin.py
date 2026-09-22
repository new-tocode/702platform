"""Shared admin building blocks, plus the read-only view of the audit trail."""

from django.contrib import admin

from .models import AuditLog
from .roles import get_role


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


class ProfileNameMixin:
    """列表页的「姓名」列。

    后台认的是 ``Profile.full_name``（``User`` 的 first_name/last_name 已弃用、
    不出现在任何界面上），用户列表与各身份名册都要这一列，所以收在这里。
    """

    @admin.display(description="姓名", ordering="profile__full_name")
    def profile_name(self, obj):
        return obj.profile.full_name


class RoleRosterAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    """一张身份名册：只读、能搜、点得进详情，顶上说明这个身份从哪来。

    对象身份（项目组联系人、项目组成员）尤其需要那句话——它们只能由业务动作
    产生，所以这里**不提供任何分配入口**，想改归属得去项目组页。全局身份的
    授予与撤销走用户列表页的批量动作，这里同样只负责看。

    子类给出 ``role_key``（取 :mod:`core.roles` 里登记的那条）、``list_display``
    与 ``get_queryset`` 即可。
    """

    role_key = None
    change_list_template = "admin/role_roster_changelist.html"

    def changelist_view(self, request, extra_context=None):
        role = get_role(self.role_key) if self.role_key else None
        extra_context = {
            **(extra_context or {}),
            "role_summary": role.summary if role else "",
        }
        return super().changelist_view(request, extra_context=extra_context)


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
