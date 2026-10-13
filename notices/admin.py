"""后台：发布公告，以及只读地查私信。

私信那张表**只给看不给动**（理由见 ``../notices/README.md`` §7）：加了改与删，
改的就是成员自己那一页上的东西。
"""

import logging

from django.contrib import admin
from django.utils.text import Truncator

from core.admin import ReadOnlyAdminMixin
from core.audit import record_audit

from .forms import NoticeAdminForm
from .models import DirectMessage, Notice
from .selectors import display_name


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


@admin.register(DirectMessage)
class DirectMessageAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    """成员之间的私信：查得到，改不了、删不掉、加不出来。

    收件人报一条骚扰，管理员能在这里按人、按时间、按正文找到它——这就是这张表
    在后台的全部用途。**删除也关掉**（``AuditLogAdmin`` 之外的只读表都交给 Django
    权限，这一张是例外）：删一条私信会连收信人「我的消息」里那一行一起带走
    （外键 ``CASCADE``），那是在动成员自己的东西，不是运维的便利。
    """

    # 账号名（唯一、稳定）与姓名（认人靠它，空着回落账号名）都摆出来：后台看这一页
    # 就是为了认出「谁给谁发了什么」，少点一次比少一列好。
    list_display = (
        "created_at",
        "sender",
        "sender_name",
        "recipient",
        "recipient_name",
        "body_chars",
        "body_preview",
    )
    list_filter = ("created_at",)
    search_fields = (
        "sender__username",
        "sender__profile__full_name",
        "recipient__username",
        "recipient__profile__full_name",
        "body",
    )
    list_select_related = ("sender__profile", "recipient__profile")
    readonly_fields = ("sender", "recipient", "body", "created_at")
    date_hierarchy = "created_at"
    ordering = ("-created_at", "-pk")

    @admin.display(description="发信人姓名", ordering="sender__profile__full_name")
    def sender_name(self, obj):
        return display_name(obj.sender)

    @admin.display(description="收信人姓名", ordering="recipient__profile__full_name")
    def recipient_name(self, obj):
        return display_name(obj.recipient)

    @admin.display(description="字数")
    def body_chars(self, obj):
        return len(obj.body)

    @admin.display(description="正文")
    def body_preview(self, obj):
        # 列表里只给一眼看个头，全文在点开的那一页——一格塞 1500 字会把表格撑破。
        return Truncator(" ".join(obj.body.split())).chars(60, truncate="…")

    def has_delete_permission(self, request, obj=None):
        return False
