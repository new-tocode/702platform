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

    def has_change_equipmentborrow_permission(self, request):
        """``mark_returned`` 动作的门槛：确有本模型的修改权限。

        Django 对 ``@admin.action(permissions=[...])`` 的自定义权限有系统检查
        （``admin.E129``），会要求这个同名方法存在——所以这层是**框架强制**的，
        不是可选装饰。默认查 ``equipment.change_equipmentborrow``：超级用户与
        「管理员」组天然为真，只挂 view 的观察者为假。

        为什么不复用 ``has_change_permission``：它被本类覆写成了 ``is_admin``，
        而 ``is_admin`` 就是 ``is_staff``（``core/permissions.py:21``），任何工作人员
        都通过——那正是这里要挡住的只读观察者。详见 ``mark_returned`` 上的注释。
        """
        return request.user.has_perm("equipment.change_equipmentborrow")

    # 这个动作必须**绕开** ``permissions=["change"]``，改查一条真实的模型权限。
    #
    # 两个坑叠在一起，才会让一个只挂 ``view_equipmentborrow`` 的 staff 在列表页
    # 拿得到这个动作、提交后借用记录真的变成已归还、库存真的加回去（实测确认过）：
    #
    #   1. 不声明 ``permissions`` 时 Django 对所有人放行——这是默认行为，
    #      ``_filter_actions_by_permissions`` 只过滤带 ``allowed_permissions`` 的动作。
    #   2. 声明 ``permissions=["change"]`` 在这一屏**等于没声明**：它查到的是本类
    #      覆写过的 ``has_change_permission``，而那是 ``is_admin`` —— ``is_admin``
    #      就是 ``is_staff``（``core/permissions.py:21``），于是任何 staff 都通过。
    #
    # 所以这里查 ``equipment.change_equipmentborrow`` 这条模型权限：它在 Django 的
    # 默认权限集里（每个模型都有 add/change/delete/view 四条），不必建自定义权限，
    # 也不需要迁移。超级用户和「管理员」组天然permission为真，只读观察者为假。
    #
    # 与前台的分工：前台归还（``equipment/views.py:132``）按 ``is_admin`` 放行，
    # 那是**成员自助**通道——staff 也是社团成员，借用后自己还自己的，天经地义。
    # 后台这一屏是**管理员代他人归还**，改的是别人的记录与公共库存，门槛理应更高。
    #
    # 回归用例：``equipment.tests.EquipmentAcceptanceTests.test_view_only_observer_cannot_mark_a_borrow_returned``。
    @admin.action(
        permissions=["change_equipmentborrow"],
        description="将选中的借用记录标记为已归还",
    )
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
