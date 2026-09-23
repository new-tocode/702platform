"""Register the account-related member operation entries and its global roles."""

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
    verbose_name = "账号与成员"

    def ready(self):
        from core.registry import register_entry
        from core.roles import Scope, register_role
        from . import signals  # noqa: F401

        register_entry(
            key="accounts.profile",
            label=_("个人信息"),
            description=_("查看和维护个人资料"),
            url_name="accounts:profile",
            sort_order=10,
        )
        register_entry(
            key="accounts.password",
            label=_("修改密码"),
            description=_("更新登录密码"),
            url_name="accounts:password_change",
            sort_order=20,
        )
        # 四种全局身份：与任何对象无关，管理员可以在后台批量授予与撤销。
        register_role(
            key="admin",
            label="管理员",
            summary=(
                "可进入管理后台；项目组创建申请由全体管理员审核，任一人同意即通过。"
                "注意它与「超级用户」是同一个开关组合，改它会同时影响后台的进入权限。"
            ),
            scope=Scope.GLOBAL,
            sort_order=10,
        )
        register_role(
            key="reviewer",
            label="评审人",
            summary="由管理员授予的评审资格；只有持有它的人才会被抽为项目书的评审人。",
            scope=Scope.GLOBAL,
            sort_order=20,
        )
        register_role(
            key="preliminary_reviewer",
            label="初审人",
            summary=(
                "由管理员授予的初审资格；每轮送审先由 1 名初审人过闸，"
                "初审通过后才分配评审人。与评审资格相互独立。"
            ),
            scope=Scope.GLOBAL,
            sort_order=30,
        )
        register_role(
            key="super_reviewer",
            label="超级评审",
            summary=(
                "由管理员授予；可看到全部进行中的轮次并一票敲定，"
                "不接常规评审任务。与评审资格相互独立。"
            ),
            scope=Scope.GLOBAL,
            sort_order=40,
        )
