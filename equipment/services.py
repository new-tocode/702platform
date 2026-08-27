"""Transactional operations for changing equipment inventory."""

import logging

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from .models import Equipment, EquipmentBorrow


logger = logging.getLogger(__name__)


class EquipmentUnavailable(Exception):
    """Raised when an active equipment item has no remaining units."""


class BorrowAlreadyReturned(Exception):
    """Raised when a second return is attempted."""


@transaction.atomic
def create_borrow(*, equipment_id, borrower, planned_return_date, remark, actor):
    """Create a borrow and decrement stock while holding the equipment row lock."""
    equipment = Equipment.objects.select_for_update().get(
        pk=equipment_id,
        is_active=True,
    )
    if equipment.available_count < 1:
        logger.warning(
            "equipment.borrow.failure equipment_id=%s borrower_id=%s actor=%s reason=out_of_stock",
            equipment.pk,
            borrower.pk,
            actor.get_username(),
        )
        raise EquipmentUnavailable

    borrow = EquipmentBorrow.objects.create(
        equipment=equipment,
        borrower=borrower,
        borrow_date=timezone.localdate(),
        planned_return_date=planned_return_date,
        remark=remark,
        status=EquipmentBorrow.BORROWED,
    )
    equipment.available_count -= 1
    equipment.save(update_fields=["available_count", "updated_at"])
    logger.info(
        "equipment.borrow.success borrow_id=%s equipment_id=%s borrower_id=%s actor=%s available_after=%s",
        borrow.pk,
        equipment.pk,
        borrower.pk,
        actor.get_username(),
        equipment.available_count,
    )
    return borrow


@transaction.atomic
def return_borrow(*, borrow_id, actor):
    """Return an authorized active borrow and restore one inventory unit."""
    borrow = EquipmentBorrow.objects.select_for_update().select_related("equipment").get(
        pk=borrow_id,
    )
    if not actor.is_staff and borrow.borrower_id != actor.pk:
        logger.warning(
            "equipment.return.denied borrow_id=%s actor=%s borrower_id=%s reason=not_owner",
            borrow.pk,
            actor.get_username(),
            borrow.borrower_id,
        )
        raise PermissionDenied
    if borrow.status == EquipmentBorrow.RETURNED:
        logger.warning(
            "equipment.return.failure borrow_id=%s actor=%s reason=already_returned",
            borrow.pk,
            actor.get_username(),
        )
        raise BorrowAlreadyReturned

    equipment = Equipment.objects.select_for_update().get(pk=borrow.equipment_id)
    borrow.status = EquipmentBorrow.RETURNED
    borrow.actual_return_date = timezone.localdate()
    borrow.save(update_fields=["status", "actual_return_date", "updated_at"])
    if equipment.available_count < equipment.total_count:
        equipment.available_count += 1
        equipment.save(update_fields=["available_count", "updated_at"])
    else:
        # Keep the invariant even if an administrator manually corrected the
        # inventory while this unit was borrowed.
        logger.warning(
            "equipment.return.inventory_invariant borrow_id=%s equipment_id=%s available=%s total=%s",
            borrow.pk,
            equipment.pk,
            equipment.available_count,
            equipment.total_count,
        )

    logger.info(
        "equipment.return.success borrow_id=%s equipment_id=%s borrower_id=%s actor=%s available_after=%s",
        borrow.pk,
        equipment.pk,
        borrow.borrower_id,
        actor.get_username(),
        equipment.available_count,
    )
    return borrow
