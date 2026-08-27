"""Register the account-related member operation entries."""

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
    verbose_name = "账号与成员"

    def ready(self):
        from core.registry import register_entry
        from . import signals  # noqa: F401

        register_entry(
            key="accounts.profile",
            label="个人信息",
            description="查看和维护个人资料",
            url_name="accounts:profile",
            sort_order=10,
        )
        register_entry(
            key="accounts.password",
            label="修改密码",
            description="更新登录密码",
            url_name="accounts:password_change",
            sort_order=20,
        )
