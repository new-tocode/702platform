"""Register equipment-related member operation entries."""

from django.apps import AppConfig


class EquipmentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "equipment"
    verbose_name = "设备管理"

    def ready(self):
        from core.registry import register_entry
        from projects.permissions import can_use_equipment

        register_entry(
            key="equipment.borrow",
            label="设备借用",
            description="查看可用设备并登记借用",
            url_name="equipment:list",
            visible_when=can_use_equipment,
            sort_order=60,
        )
        register_entry(
            key="equipment.records",
            label="借用记录",
            description="查看和处理自己的设备记录",
            url_name="equipment_borrows:list",
            sort_order=70,
        )
