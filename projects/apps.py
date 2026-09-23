"""Register the project-group member operation entry and its two object roles."""

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ProjectsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "projects"
    verbose_name = "项目组"

    def ready(self):
        from core.registry import register_entry
        from core.roles import Scope, register_role

        register_entry(
            key="projects.groups",
            label=_("项目组"),
            description=_("查看项目组、联系人和成员"),
            url_name="projects:group_list",
            sort_order=40,
        )
        # 这两种身份不挂在自己身上，而是「账号 + 项目组」的产物，所以后台只给
        # 名册、不给分配入口（见 core.roles 的说明）。
        register_role(
            key="project_contact",
            label="项目组联系人",
            summary=(
                "身份来自「创建项目组申请通过」或组内转让，每个项目组一位，不单独发放；"
                "想变更归属，请在项目组里操作。"
            ),
            scope=Scope.OBJECT,
            sort_order=50,
        )
        register_role(
            key="project_member",
            label="项目组成员",
            summary=(
                "身份来自「申请加入项目组 → 联系人审批通过」，或建组时申请人自动入组；"
                "想变更归属，请在项目组里操作。"
            ),
            scope=Scope.OBJECT,
            sort_order=60,
        )
