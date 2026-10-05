"""Helpers for recording structured, non-secret audit events."""

import logging

from django.conf import settings

from .models import AuditLog


logger = logging.getLogger(__name__)


def get_client_ip(request):
    """请求的真实来源 IP——全站唯一的取 IP 口径。

    审计日志、登录成功/失败日志、锁定审计都走这里；django-axes 的「按 IP 计数」
    也经 ``settings.AXES_CLIENT_IP_CALLABLE`` 指到同一个函数。同一个问题只有
    一个答案，否则「锁了谁」与「记了谁」迟早对不上。

    **默认只信 ``REMOTE_ADDR``**，因为那在直连部署下无法伪造。但本站是
    nginx 反代到 127.0.0.1:8000 的（见 ``deploy/nginx-club702.conf``），此时
    ``REMOTE_ADDR`` 恒为 127.0.0.1：审计日志里所有事件的来源 IP 都成了同一个值，
    而 axes 的「按 IP 锁定」会把全站用户算成同一个人——任意 10 次失败就锁死
    所有人的登录，且事后查不出是谁在试。

    所以另设 ``TRUST_FORWARDED_FOR``，**只在 nginx 确实会覆写该头时才打开**。
    取值取**最后一段**：无论 nginx 用 ``$remote_addr`` 覆写、还是用
    ``$proxy_add_x_forwarded_for`` 追加，最后一段都是它亲眼看到的对端地址；
    客户端自己塞进去的部分只会落在前面。
    """
    if not request:
        return None
    if getattr(settings, "TRUST_FORWARDED_FOR", False):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
        if hops:
            return hops[-1]
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
