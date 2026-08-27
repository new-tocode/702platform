"""Register the project-group member operation entry."""

from django.apps import AppConfig


class ProjectsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "projects"
    verbose_name = "项目组"

    def ready(self):
        from core.registry import register_entry

        register_entry(
            key="projects.groups",
            label="项目组",
            description="查看项目组、组长和成员",
            url_name="projects:group_list",
            sort_order=40,
        )
