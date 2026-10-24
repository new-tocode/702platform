"""后台只读视图：答辩申请与它的讨论记录。

成员侧才是写入口（项目组管理页发起、详情页修改／评论／关闭）。后台只负责
「出了事能查」——加、改、删一律关掉，与审计日志、各类申请表的处置一致。
"""

from django.contrib import admin

from core.admin import ReadOnlyAdminMixin

from .models import DefenseComment, DefenseRequest


class DefenseCommentInline(admin.TabularInline):
    model = DefenseComment
    extra = 0
    can_delete = False
    fields = ("created_at", "author", "kind", "body")
    readonly_fields = fields
    ordering = ("created_at", "id")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(DefenseRequest)
class DefenseRequestAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = (
        "id",
        "group",
        "applicant",
        "status",
        "created_at",
        "closed_at",
    )
    list_filter = ("status", "created_at")
    search_fields = (
        "group__name",
        "applicant__username",
        "applicant__profile__full_name",
        "content",
    )
    list_select_related = ("group", "applicant", "closed_by")
    date_hierarchy = "created_at"
    ordering = ("-created_at", "-id")
    inlines = (DefenseCommentInline,)

    def has_delete_permission(self, request, obj=None):
        # 与 ReadOnlyAdminMixin 的其他表不同，这张表的删除会连讨论与消息一起
        # 级联带走；成员侧的「关闭」才是业务上的退场方式。
        return False
