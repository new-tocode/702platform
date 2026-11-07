"""App config for offline mock-defense scheduling."""

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class DefensesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "defenses"
    verbose_name = "线下答辩"

    def ready(self):
        from core.registry import register_entry

        register_entry(
            key="defenses.schedule",
            label=_("线下答辩"),
            description=_("查看项目组的线下模拟答辩安排与讨论"),
            url_name="defenses:schedule",
            sort_order=75,
        )
