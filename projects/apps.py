"""Register the project-group member operation entry."""

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ProjectsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "projects"
    verbose_name = "项目组"

    def ready(self):
        from core.registry import register_entry

        register_entry(
            key="projects.groups",
            label=_("项目组"),
            description=_("查看项目组、联系人和成员"),
            url_name="projects:group_list",
            sort_order=40,
        )
