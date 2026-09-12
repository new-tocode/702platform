"""Transactional project-group operations shared by member views.

Domain rules that must not be duplicated live here (mirroring the style of
``equipment.services``): each function validates, mutates inside a transaction,
and writes an audit record.
"""

import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from core.audit import record_audit

from .models import GroupJoinRequest


logger = logging.getLogger(__name__)


class JoinRequestError(Exception):
    """The membership application cannot be created or decided."""


class GroupManagementError(Exception):
    """A group management action violates a business rule."""


def apply_to_group(*, group, applicant, message="", request=None):
    """Create (or refresh) a pending application to join a group."""
    if not applicant.is_authenticated:
        raise JoinRequestError("请先登录。")
    if group.members.filter(pk=applicant.pk).exists():
        raise JoinRequestError("你已经是该项目组成员。")
    try:
        with transaction.atomic():
            join_request, created = GroupJoinRequest.objects.get_or_create(
                group=group,
                applicant=applicant,
                status=GroupJoinRequest.PENDING,
                defaults={"message": message},
            )
            if not created and message:
                join_request.message = message
                join_request.save(update_fields=["message", "updated_at"])
    except IntegrityError as exc:  # concurrent duplicate pending application
        raise JoinRequestError("你已经提交过申请，请等待联系人审核。") from exc
    record_audit(
        action="projects.join.apply",
        user=applicant,
        target=join_request,
        detail={"group_id": group.pk},
        request=request,
    )
    logger.info(
        "project_group.join.apply group_id=%s applicant_id=%s created=%s",
        group.pk,
        applicant.pk,
        created,
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return join_request


def approve_join_request(*, join_request, actor, request=None):
    """Approve a pending application and add the applicant to the group."""
    with transaction.atomic():
        locked = (
            GroupJoinRequest.objects.select_for_update()
            .select_related("group")
            .get(pk=join_request.pk)
        )
        if locked.status != GroupJoinRequest.PENDING:
            raise JoinRequestError("该申请已被处理。")
        locked.status = GroupJoinRequest.APPROVED
        locked.decided_by = actor
        locked.decided_at = timezone.now()
        locked.save(update_fields=["status", "decided_by", "decided_at", "updated_at"])
        locked.group.members.add(locked.applicant_id)
    record_audit(
        action="projects.join.approve",
        user=actor,
        target=locked,
        detail={"group_id": locked.group_id, "applicant_id": locked.applicant_id},
        request=request,
    )
    return locked


def reject_join_request(*, join_request, actor, request=None):
    """Reject a pending application; the applicant may apply again later."""
    with transaction.atomic():
        locked = GroupJoinRequest.objects.select_for_update().get(pk=join_request.pk)
        if locked.status != GroupJoinRequest.PENDING:
            raise JoinRequestError("该申请已被处理。")
        locked.status = GroupJoinRequest.REJECTED
        locked.decided_by = actor
        locked.decided_at = timezone.now()
        locked.save(update_fields=["status", "decided_by", "decided_at", "updated_at"])
    record_audit(
        action="projects.join.reject",
        user=actor,
        target=locked,
        detail={"group_id": locked.group_id, "applicant_id": locked.applicant_id},
        request=request,
    )
    return locked


def remove_group_member(*, group, member, actor, request=None):
    """Remove a member; the current contact must be transferred first."""
    if group.leader_id == member.pk:
        raise GroupManagementError("不能移除项目组联系人，请先转让联系人。")
    with transaction.atomic():
        group.members.remove(member)
    record_audit(
        action="projects.member.remove",
        user=actor,
        target=group,
        detail={"member_id": member.pk},
        request=request,
    )
    return group


def transfer_contact(*, group, new_contact, actor, request=None):
    """Transfer the contact role to another member.

    The outgoing contact stays in the member list (``ProjectGroup.save`` only
    ever adds the contact, never removes one).
    """
    if not group.members.filter(pk=new_contact.pk).exists():
        raise GroupManagementError("新联系人必须是该项目组成员。")
    previous_contact_id = group.leader_id
    with transaction.atomic():
        group.leader = new_contact
        group.save(update_fields=["leader", "updated_at"])
    record_audit(
        action="projects.contact.transfer",
        user=actor,
        target=group,
        detail={
            "previous_contact_id": previous_contact_id,
            "new_contact_id": new_contact.pk,
        },
        request=request,
    )
    return group


def update_group_description(*, group, description, actor, request=None):
    """Update a group's public description."""
    group.description = description
    group.save(update_fields=["description", "updated_at"])
    record_audit(
        action="projects.group.description.update",
        user=actor,
        target=group,
        detail={},
        request=request,
    )
    return group
