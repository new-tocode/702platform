from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "平台核心"

    def ready(self):
        from .registry import register_entry

        register_entry(
            key="core.audit",
            label="审计日志",
            description="查看平台关键操作记录",
            url_name="admin:core_auditlog_changelist",
            required_permission="core.view_auditlog",
            staff_only=True,
            sort_order=90,
        )
