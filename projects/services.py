"""Transactional project-group operations shared by member views.

Domain rules that must not be duplicated live here (mirroring the style of
``equipment.services``): each function validates, mutates inside a transaction,
and writes an audit record.
"""

import logging

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.audit import record_audit

from .models import (
    MAX_ADVISORS_PER_GROUP,
    GroupCreateRequest,
    GroupJoinRequest,
    ProjectAdvisor,
    ProjectGroup,
)


logger = logging.getLogger(__name__)


class JoinRequestError(Exception):
    """The membership application cannot be created or decided."""


class GroupManagementError(Exception):
    """A group management action violates a business rule."""


class GroupCreateRequestError(Exception):
    """创建项目组的申请不能被提交或处理。"""


def _advisor_names_or_raise(names, error_cls):
    """归一化指导老师姓名，超过上限时抛 ``error_cls``。

    申请建组与维护组信息两处的归一化和上限文案逐字相同，只有异常类不同
    （各自服务自己的入口），所以由调用方指定该抛哪一种。
    """
    cleaned = [name.strip() for name in names if name.strip()]
    if len(cleaned) > MAX_ADVISORS_PER_GROUP:
        raise error_cls(
            _("指导老师最多 %(max)s 位。") % {"max": MAX_ADVISORS_PER_GROUP}
        )
    return cleaned


def _advisor_slots(names):
    """把已填写的指导老师姓名摊回三个固定槽位，空槽位写空串。"""
    return {
        f"advisor_{slot + 1}": (names[slot] if slot < len(names) else "")
        for slot in range(MAX_ADVISORS_PER_GROUP)
    }


def apply_to_group(*, group, applicant, message="", request=None):
    """Create (or refresh) a pending application to join a group."""
    if not applicant.is_authenticated:
        raise JoinRequestError(_("请先登录。"))
    if group.members.filter(pk=applicant.pk).exists():
        raise JoinRequestError(_("你已经是该项目组成员。"))
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
        raise JoinRequestError(_("你已经提交过申请，请等待联系人审核。")) from exc
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
            raise JoinRequestError(_("该申请已被处理。"))
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
            raise JoinRequestError(_("该申请已被处理。"))
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


def apply_to_create_group(
    *,
    applicant,
    name,
    description,
    college="",
    advisor_names=(),
    request=None,
):
    """Create (or refresh) the applicant's pending request to found a group.

    Any logged-in member may apply. Applying again while one is pending rewrites
    that same record rather than adding a second — the partial unique constraint
    on ``(applicant) WHERE status='pending'`` allows only one.
    """
    if not applicant.is_authenticated:
        raise GroupCreateRequestError(_("请先登录。"))
    names = _advisor_names_or_raise(advisor_names, GroupCreateRequestError)
    fields = {
        "name": name,
        "description": description,
        "college": college,
        **_advisor_slots(names),
    }
    try:
        with transaction.atomic():
            create_request, created = GroupCreateRequest.objects.get_or_create(
                applicant=applicant,
                status=GroupCreateRequest.PENDING,
                defaults=fields,
            )
            if not created:
                for field, value in fields.items():
                    setattr(create_request, field, value)
                create_request.save(update_fields=[*fields, "updated_at"])
    except IntegrityError as exc:  # 并发提交撞上部分唯一约束
        raise GroupCreateRequestError(
            _("你已经提交过创建项目组的申请，请等待管理员审核。")
        ) from exc
    record_audit(
        action="projects.group.create.apply",
        user=applicant,
        target=create_request,
        detail={"name": name, "refreshed": not created},
        request=request,
    )
    logger.info(
        "project_group.create.apply applicant_id=%s create_request_id=%s created=%s",
        applicant.pk,
        create_request.pk,
        created,
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return create_request


def approve_create_request(*, create_request, actor, request=None):
    """Approve a pending creation request and found the project group.

    One administrator's approval is enough: the row is locked and its status
    re-checked inside the transaction, so a second administrator clicking at the
    same time is told the request is already handled instead of creating a
    duplicate group. The applicant becomes the new group's contact.
    """
    with transaction.atomic():
        locked = (
            GroupCreateRequest.objects.select_for_update()
            .select_related("applicant")
            .get(pk=create_request.pk)
        )
        if locked.status != GroupCreateRequest.PENDING:
            raise GroupCreateRequestError(_("该申请已被处理。"))
        group = ProjectGroup.objects.create(
            name=locked.name,
            leader=locked.applicant,
            description=locked.description,
            college=locked.college,
        )
        for slot, advisor_name in enumerate(locked.filled_advisor_names):
            ProjectAdvisor.objects.create(
                group=group,
                name=advisor_name,
                sort_order=slot,
            )
        locked.status = GroupCreateRequest.APPROVED
        locked.decided_by = actor
        locked.decided_at = timezone.now()
        locked.created_group = group
        locked.save(
            update_fields=[
                "status",
                "decided_by",
                "decided_at",
                "created_group",
                "updated_at",
            ]
        )
    record_audit(
        action="projects.group.create.approve",
        user=actor,
        target=locked,
        detail={"group_id": group.pk, "applicant_id": locked.applicant_id},
        request=request,
    )
    logger.info(
        "project_group.create.approve create_request_id=%s group_id=%s actor_id=%s",
        locked.pk,
        group.pk,
        actor.pk,
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return locked


def reject_create_request(*, create_request, actor, request=None):
    """Reject a pending creation request; the applicant may apply again later."""
    with transaction.atomic():
        locked = GroupCreateRequest.objects.select_for_update().get(pk=create_request.pk)
        if locked.status != GroupCreateRequest.PENDING:
            raise GroupCreateRequestError(_("该申请已被处理。"))
        locked.status = GroupCreateRequest.REJECTED
        locked.decided_by = actor
        locked.decided_at = timezone.now()
        locked.save(update_fields=["status", "decided_by", "decided_at", "updated_at"])
    record_audit(
        action="projects.group.create.reject",
        user=actor,
        target=locked,
        detail={"applicant_id": locked.applicant_id},
        request=request,
    )
    return locked


def remove_group_member(*, group, member, actor, request=None):
    """Remove a member; the current contact must be transferred first."""
    if group.leader_id == member.pk:
        raise GroupManagementError(_("不能移除项目组联系人，请先转让联系人。"))
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
        raise GroupManagementError(_("新联系人必须是该项目组成员。"))
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


def update_group_info(*, group, college, advisor_names, actor, request=None):
    """Update a group's college and its advisors (at most ``MAX_ADVISORS_PER_GROUP``).

    Advisors map onto fixed slots, so editing a name keeps that row's identity
    instead of replacing every row on each save. A blank slot deletes the row
    it held, and the remaining names close up to slots 0..n-1 — which is what
    keeps the ``(group, sort_order)`` uniqueness constraint satisfiable.
    """
    names = _advisor_names_or_raise(advisor_names, GroupManagementError)
    with transaction.atomic():
        group.college = college
        group.save(update_fields=["college", "updated_at"])
        existing = {advisor.sort_order: advisor for advisor in group.advisors.all()}
        for slot in range(MAX_ADVISORS_PER_GROUP):
            name = names[slot] if slot < len(names) else ""
            advisor = existing.get(slot)
            if not name:
                if advisor:
                    advisor.delete()
            elif not advisor:
                ProjectAdvisor.objects.create(group=group, name=name, sort_order=slot)
            elif advisor.name != name:
                advisor.name = name
                advisor.save(update_fields=["name", "updated_at"])
    record_audit(
        action="projects.group.info.update",
        user=actor,
        target=group,
        detail={"college": college, "advisors": names},
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
