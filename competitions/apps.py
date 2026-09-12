"""Register the competition manager operation entry."""

from django.apps import AppConfig


class CompetitionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "competitions"
    verbose_name = "竞赛"

    def ready(self):
        from core.registry import register_entry

        register_entry(
            key="competitions.registration",
            label="竞赛信息",
            description="查看竞赛信息；项目组联系人可为项目组报名",
            url_name="competitions:list",
            sort_order=50,
        )
