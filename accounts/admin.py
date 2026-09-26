"""Django Admin configuration for account provisioning and password resets."""

import logging

from django.contrib import admin, messages
from django.contrib.auth.admin import GroupAdmin as DjangoGroupAdmin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import Group
from django.db.models import Count, Q

from core.admin import ProfileNameMixin, RoleRosterAdmin
from core.audit import record_audit
from reviews import lifecycle

from .forms import (
    AdminPasswordChangeForm,
    AdminUserChangeForm,
    AdminUserCreationForm,
)
from .models import (
    AdminRole,
    PreliminaryReviewerRole,
    Profile,
    ReviewerRole,
    SuperReviewerRole,
    User,
)
from .services import set_qualification


logger = logging.getLogger(__name__)


def _qualification_action(*, flag, label, value):
    """造一个「授予／撤销某种资格」的批量动作。

    六个动作只有字段名、文案与取值不同，所以由这里生成——八份各自的
    ``@admin.action`` 只会让「谁在改资格、怎么留痕」散成八处。

    ``permissions=["change"]`` 是这个装饰器的**白名单**功能：不声明时 Django
    对所有人放行，只挂 ``view_user`` 的只读观察者也能提交这个动作。那道关不
    是装饰性的——``set_qualification`` 是给程序调用的服务函数，不看请求是谁
    发的，所以这里是唯一的 HTTP 门槛。
    """

    @admin.action(
        permissions=["change"],
        description=f"{'授予' if value else '撤销'}{label}资格",
    )
    def action(modeladmin, request, queryset):
        changed = set_qualification(
            users=queryset,
            flag=flag,
            value=value,
            actor=request.user,
            request=request,
        )
        verb = "授予" if value else "撤销"
        if changed:
            modeladmin.message_user(
                request,
                f"已{verb}{label}资格：{changed} 人。",
                messages.SUCCESS,
            )
        else:
            modeladmin.message_user(
                request,
                f"所选账号的{label}资格没有变化。",
                messages.WARNING,
            )

    action.__name__ = f"{'grant' if value else 'revoke'}_{flag}"
    return action


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "full_name",
        "student_id",
        "college",
        "major",
        "specialty",
        "phone",
    )
    search_fields = (
        "user__username",
        "full_name",
        "student_id",
        "college",
        "major",
        "specialty",
    )
    list_select_related = ("user",)


@admin.register(User)
class UserAdmin(ProfileNameMixin, DjangoUserAdmin):
    """Expose the forced-change flag and keep reset semantics explicit.

    资格仍然可以在用户编辑页逐个勾选；列表页另有六个批量动作，一次给一批人
    授予或撤销评审／初审／超级评审资格。**没有管理员的批量授予**——那等于一次
    给一批人开后台，应当逐个确认。
    """

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
                    "is_reviewer",
                    "is_preliminary_reviewer",
                    "is_super_reviewer",
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
                    "is_reviewer",
                    "is_preliminary_reviewer",
                    "is_super_reviewer",
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
        "is_reviewer",
        "is_preliminary_reviewer",
        "is_super_reviewer",
        "is_active",
    )
    list_filter = (
        "must_change_password",
        "is_staff",
        "is_superuser",
        "is_reviewer",
        "is_preliminary_reviewer",
        "is_super_reviewer",
        "is_active",
        "groups",
    )
    search_fields = ("username", "email", "profile__full_name")
    list_select_related = ("profile",)
    actions = (
        _qualification_action(flag="is_reviewer", label="评审", value=True),
        _qualification_action(flag="is_reviewer", label="评审", value=False),
        _qualification_action(flag="is_preliminary_reviewer", label="初审", value=True),
        _qualification_action(flag="is_preliminary_reviewer", label="初审", value=False),
        _qualification_action(flag="is_super_reviewer", label="超级评审", value=True),
        _qualification_action(flag="is_super_reviewer", label="超级评审", value=False),
    )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if hasattr(form, "save_profile"):
            form.save_profile(obj)
        record_audit(
            action="accounts.user.create" if not change else "accounts.user.update",
            user=request.user,
            target=obj,
            detail={"must_change_password": obj.must_change_password},
            request=request,
        )
        logger.info(
            "admin.user.save operator=%s target=%s target_id=%s created=%s must_change_password=%s",
            request.user.get_username(),
            obj.get_username(),
            obj.pk,
            not change,
            obj.must_change_password,
            extra={"request_id": getattr(request, "request_id", "-")},
        )


admin.site.unregister(Group)


@admin.register(Group)
class GroupAdmin(DjangoGroupAdmin):
    """Extend the built-in group admin with a read-only member overview."""

    list_display = ("name", "member_count")
    search_fields = ("name", "user__username", "user__profile__full_name")
    fieldsets = (
        (None, {"fields": ("name", "permissions")}),
        ("组内用户", {"fields": ("members_overview",)}),
    )
    readonly_fields = ("members_overview",)

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .annotate(_member_count=Count("user", distinct=True))
            .prefetch_related("user_set__profile")
        )

    @admin.display(description="用户数", ordering="_member_count")
    def member_count(self, obj):
        return obj._member_count

    @admin.display(description="属于该组的用户")
    def members_overview(self, obj):
        if not obj.pk:
            return "保存后可查看组内用户。"
        names = [
            user.profile.full_name or user.username
            for user in obj.user_set.all()
        ]
        return "、".join(names) or "（暂无用户）"


# --- 四张全局身份名册 -------------------------------------------------------
#
# 身份本身在 User 的布尔字段上（见 models 里的 proxy），这里把它们摆成四张
# 只读名册，好回答「这个身份上都有谁」。名册不给分配入口：授予与撤销走用户
# 列表页的六个批量动作，判定仍归 reviews.permissions。
#
# 这两处「组」不是身份，别混淆：auth.Group 只用于内部通知的投递范围
# （上面的 GroupAdmin），ProjectGroup 是业务上的项目组。


def _role_labels(user):
    """这个人身上有哪几重身份，顿号连起来；一重都没有时给个占位符。"""
    labels = []
    if user.is_staff or user.is_superuser:
        labels.append("管理员")
    if user.is_reviewer:
        labels.append("评审人")
    if user.is_preliminary_reviewer:
        labels.append("初审人")
    if user.is_super_reviewer:
        labels.append("超级评审")
    return "、".join(labels) or "—"


class GlobalRoleRosterAdmin(ProfileNameMixin, RoleRosterAdmin):
    """四种全局身份名册的公共部分。

    它们都挂在账号上，所以列、搜索、排序一模一样，不同的只是「谁是这一家的人」
    ——那由各子类的 ``get_queryset`` 给出。
    """

    list_display = ("username", "profile_name", "college", "roles", "is_active")
    search_fields = ("username", "profile__full_name", "profile__student_id")
    list_select_related = ("profile",)
    list_filter = ("is_active",)
    ordering = ("username",)

    @admin.display(description="学院", ordering="profile__college")
    def college(self, obj):
        return obj.profile.college

    @admin.display(description="全部身份")
    def roles(self, obj):
        return _role_labels(obj)

    def _with_pending(self, queryset, *, stage):
        """补一列「手上有几件待办」——一次 annotate，不是每行查一次。"""
        from reviews.models import ReviewTask

        return queryset.annotate(
            pending_count=Count(
                "review_tasks",
                filter=Q(
                    review_tasks__status=ReviewTask.PENDING,
                    review_tasks__stage=stage,
                ),
            )
        )

    @admin.display(description="手上待办", ordering="pending_count")
    def pending(self, obj):
        return getattr(obj, "pending_count", 0) or "—"


@admin.register(AdminRole)
class AdminRoleAdmin(GlobalRoleRosterAdmin):
    role_key = "admin"
    list_display = (
        "username",
        "profile_name",
        "college",
        "roles",
        "is_superuser",
        "is_active",
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .filter(Q(is_staff=True) | Q(is_superuser=True))
        )


@admin.register(ReviewerRole)
class ReviewerRoleAdmin(GlobalRoleRosterAdmin):
    role_key = "reviewer"
    list_display = (
        "username",
        "profile_name",
        "college",
        "roles",
        "pending",
        "is_active",
    )

    def get_queryset(self, request):
        return self._with_pending(
            super().get_queryset(request).filter(is_reviewer=True),
            stage=lifecycle.STAGE_REVIEW,
        )


@admin.register(PreliminaryReviewerRole)
class PreliminaryReviewerRoleAdmin(GlobalRoleRosterAdmin):
    role_key = "preliminary_reviewer"
    list_display = (
        "username",
        "profile_name",
        "college",
        "roles",
        "pending",
        "is_active",
    )

    def get_queryset(self, request):
        return self._with_pending(
            super().get_queryset(request).filter(is_preliminary_reviewer=True),
            stage=lifecycle.STAGE_PRELIMINARY,
        )


@admin.register(SuperReviewerRole)
class SuperReviewerRoleAdmin(GlobalRoleRosterAdmin):
    role_key = "super_reviewer"

    def get_queryset(self, request):
        return super().get_queryset(request).filter(is_super_reviewer=True)
