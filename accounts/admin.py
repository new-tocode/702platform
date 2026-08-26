"""Django Admin configuration for account provisioning and password resets."""

import logging

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .forms import (
    AdminPasswordChangeForm,
    AdminUserChangeForm,
    AdminUserCreationForm,
)
from .models import Profile, User


logger = logging.getLogger(__name__)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "full_name", "student_id", "college", "major", "phone")
    search_fields = ("user__username", "full_name", "student_id", "college", "major")
    list_select_related = ("user",)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Expose the forced-change flag and keep reset semantics explicit."""

    form = AdminUserChangeForm
    add_form = AdminUserCreationForm
    change_password_form = AdminPasswordChangeForm
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("个人信息", {"fields": ("email", "full_name")}),
        (
            "权限",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        ("重要日期", {"fields": ("last_login", "date_joined")}),
        (
            "平台账号策略",
            {
                "fields": ("must_change_password",),
                "description": "管理员重置密码后应保持勾选，成员首次登录成功改密后自动取消。",
            },
        ),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "username",
                    "email",
                    "full_name",
                    "password1",
                    "password2",
                ),
            },
        ),
    )
    list_display = (
        "username",
        "email",
        "profile_name",
        "must_change_password",
        "is_staff",
        "is_active",
    )
    list_filter = ("must_change_password", "is_staff", "is_superuser", "is_active", "groups")
    search_fields = ("username", "email", "profile__full_name")
    list_select_related = ("profile",)

    @admin.display(description="姓名", ordering="profile__full_name")
    def profile_name(self, obj):
        return obj.profile.full_name


    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if hasattr(form, "save_profile"):
            form.save_profile(obj)
        logger.info(
            "admin.user.save operator=%s target=%s target_id=%s created=%s must_change_password=%s",
            request.user.get_username(),
            obj.get_username(),
            obj.pk,
            not change,
            obj.must_change_password,
            extra={"request_id": getattr(request, "request_id", "-")},
        )
