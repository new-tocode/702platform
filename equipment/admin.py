"""Django Admin configuration for equipment and borrowing records."""

import logging

from django.contrib import admin, messages

from core.audit import record_audit
from core.permissions import is_admin

from .forms import EquipmentAdminForm
from .models import Equipment, EquipmentBorrow
from .services import BorrowAlreadyReturned, return_borrow


logger = logging.getLogger(__name__)


@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    form = EquipmentAdminForm
    list_display = (
        "name",
        "category",
        "total_count",
        "available_count",
        "is_active",
        "updated_at",
    )
    list_filter = ("is_active", "category")
    search_fields = ("name", "category", "description")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("category", "name", "id")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        record_audit(
            action="equipment.create" if not change else "equipment.update",
            user=request.user,
            target=obj,
            detail={
                "total_count": obj.total_count,
                "available_count": obj.available_count,
                "is_active": obj.is_active,
            },
            request=request,
        )
        logger.info(
            "admin.equipment.save operator=%s equipment_id=%s name=%s total=%s available=%s active=%s created=%s",
            request.user.get_username(),
            obj.pk,
            obj.name,
            obj.total_count,
            obj.available_count,
            obj.is_active,
            not change,
            extra={"request_id": getattr(request, "request_id", "-")},
        )


@admin.register(EquipmentBorrow)
class EquipmentBorrowAdmin(admin.ModelAdmin):
    list_display = (
        "equipment",
        "borrower",
        "borrow_date",
        "planned_return_date",
        "status",
        "actual_return_date",
        "created_at",
    )
    list_filter = ("status", "borrow_date", "planned_return_date")
    search_fields = (
        "equipment__name",
        "borrower__username",
        "borrower__profile__full_name",
        "remark",
    )
    list_select_related = ("equipment", "borrower")
    readonly_fields = (
        "equipment",
        "borrower",
        "borrow_date",
        "planned_return_date",
        "actual_return_date",
        "status",
        "remark",
        "created_at",
        "updated_at",
    )
    actions = ("mark_returned",)
    ordering = ("-created_at", "-id")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        # Returns must go through the dedicated transactional operation.
        return is_admin(request.user)

    def has_delete_permission(self, request, obj=None):
        # Deleting an active record without returning stock would corrupt inventory.
        return False

    @admin.action(description="将选中的借用记录标记为已归还")
    def mark_returned(self, request, queryset):
        returned_count = 0
        already_returned_count = 0
        for borrow_id in queryset.values_list("pk", flat=True):
            try:
                returned_borrow = return_borrow(borrow_id=borrow_id, actor=request.user)
            except BorrowAlreadyReturned:
                already_returned_count += 1
            else:
                returned_count += 1
                record_audit(
                    action="equipment.return.admin",
                    user=request.user,
                    target=returned_borrow,
                    detail={"equipment_id": returned_borrow.equipment_id},
                    request=request,
                )
        if returned_count:
            self.message_user(
                request,
                f"已归还 {returned_count} 条借用记录。",
                messages.SUCCESS,
            )
        if already_returned_count:
            self.message_user(
                request,
                f"其中 {already_returned_count} 条记录已经归还。",
                messages.WARNING,
            )
