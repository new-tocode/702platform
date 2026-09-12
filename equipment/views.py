"""Member-facing equipment inventory and borrow records."""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from core.audit import record_audit
from projects.permissions import can_use_equipment

from .forms import EquipmentBorrowForm
from .models import Equipment, EquipmentBorrow
from .services import (
    BorrowAlreadyReturned,
    EquipmentUnavailable,
    create_borrow,
    return_borrow,
)


logger = logging.getLogger(__name__)


def _require_equipment_access(request):
    """Borrowing is limited to project-group members (and administrators)."""
    if not can_use_equipment(request.user):
        logger.warning(
            "equipment.permission.denied username=%s path=%s",
            request.user.get_username(),
            request.path,
            extra={"request_id": getattr(request, "request_id", "-")},
        )
        raise PermissionDenied


@login_required
@require_http_methods(["GET"])
def equipment_list(request):
    _require_equipment_access(request)
    equipment = Equipment.objects.filter(is_active=True).order_by(
        "category", "name", "id"
    )
    logger.info(
        "equipment.list.view count=%s username=%s",
        equipment.count(),
        request.user.get_username(),
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return render(request, "equipment/list.html", {"equipment": equipment})


@login_required
@require_http_methods(["GET", "POST"])
def equipment_borrow(request, pk):
    _require_equipment_access(request)
    equipment = get_object_or_404(Equipment, pk=pk, is_active=True)
    form = EquipmentBorrowForm(equipment, data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        try:
            borrow = create_borrow(
                equipment_id=equipment.pk,
                borrower=request.user,
                planned_return_date=form.cleaned_data["planned_return_date"],
                remark=form.cleaned_data.get("remark", ""),
                actor=request.user,
            )
        except EquipmentUnavailable:
            form.add_error(None, "该设备当前没有可借数量。")
            logger.warning(
                "equipment.borrow.failure equipment_id=%s username=%s reason=out_of_stock",
                equipment.pk,
                request.user.get_username(),
                extra={"request_id": getattr(request, "request_id", "-")},
            )
        else:
            record_audit(
                action="equipment.borrow",
                user=request.user,
                target=borrow,
                detail={"equipment_id": equipment.pk},
                request=request,
            )
            messages.success(request, f"已登记借用：{equipment.name}。")
            return redirect("equipment_borrows:list")
    elif request.method == "POST":
        logger.warning(
            "equipment.borrow.failure equipment_id=%s username=%s errors=%s",
            equipment.pk,
            request.user.get_username(),
            form.errors.as_json(),
            extra={"request_id": getattr(request, "request_id", "-")},
        )

    return render(
        request,
        "equipment/borrow_form.html",
        {"equipment": equipment, "form": form},
    )


@login_required
@require_http_methods(["GET"])
def borrow_list(request):
    if request.user.is_staff:
        borrows = EquipmentBorrow.objects.select_related(
            "equipment", "borrower"
        ).all()
        scope = "all"
    else:
        borrows = EquipmentBorrow.objects.filter(
            borrower=request.user,
        ).select_related("equipment", "borrower")
        scope = "own"
    logger.info(
        "equipment.borrow_list.view scope=%s count=%s username=%s",
        scope,
        borrows.count(),
        request.user.get_username(),
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return render(request, "equipment/borrow_list.html", {"borrows": borrows})


@login_required
@require_POST
def borrow_return(request, pk):
    borrow = get_object_or_404(
        EquipmentBorrow,
        pk=pk,
        **({} if request.user.is_staff else {"borrower": request.user}),
    )
    try:
        return_borrow(borrow_id=borrow.pk, actor=request.user)
    except BorrowAlreadyReturned:
        messages.warning(request, "该设备借用记录已经归还。")
    else:
        record_audit(
            action="equipment.return",
            user=request.user,
            target=borrow,
            detail={"equipment_id": borrow.equipment_id},
            request=request,
        )
        messages.success(request, f"已登记归还：{borrow.equipment.name}。")
    return redirect("equipment_borrows:list")
