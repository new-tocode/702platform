"""Register the notification member operation entry."""

from django.apps import AppConfig


class NoticesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "notices"
    verbose_name = "通知公告"

    def ready(self):
        from core.registry import register_entry

        register_entry(
            key="notices.internal",
            label="内部通知",
            description="查看与你所属用户组相关的通知",
            url_name="member_notices:internal_list",
            sort_order=30,
        )
