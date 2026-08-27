"""Register the competition manager operation entry."""

from django.apps import AppConfig


class CompetitionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "competitions"
    verbose_name = "竞赛"

    def ready(self):
        from core.registry import register_entry
        from .permissions import is_competition_manager

        register_entry(
            key="competitions.registration",
            label="竞赛报名",
            description="查看竞赛并为项目组登记报名",
            url_name="competitions:list",
            visible_when=is_competition_manager,
            sort_order=50,
        )
