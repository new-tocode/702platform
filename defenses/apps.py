"""App config for offline mock-defense scheduling."""

from django.apps import AppConfig


class DefensesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "defenses"
    verbose_name = "线下答辩"
