"""Helpers for recording structured, non-secret audit events."""

import logging

from .models import AuditLog


logger = logging.getLogger(__name__)


def get_client_ip(request):
    if not request:
        return None
    # Do not trust X-Forwarded-For until the deployment explicitly configures
    # a trusted proxy chain. REMOTE_ADDR is the safe default here.
    return request.META.get("REMOTE_ADDR")


def record_audit(
    *,
    action,
    user=None,
    target=None,
    detail=None,
    request=None,
):
    """Persist one audit event; callers must pass only non-sensitive details."""
    target_type = ""
    target_id = ""
    if target is not None:
        target_type = f"{target._meta.app_label}.{target._meta.model_name}"
        target_id = str(target.pk)
    request_id = getattr(request, "request_id", "") if request else ""
    ip_address = get_client_ip(request)
    audit = AuditLog.objects.create(
        action=action,
        user=user if user and user.is_authenticated else None,
        target_type=target_type,
        target_id=target_id,
        detail=detail or {},
        request_id=request_id,
        ip_address=ip_address,
    )
    logger.info(
        "audit.record action=%s audit_id=%s target=%s:%s actor=%s",
        action,
        audit.pk,
        target_type,
        target_id,
        user.get_username() if user and user.is_authenticated else "system",
        extra={"request_id": request_id or "-"},
    )
    return audit
