"""Database-backed audit trail for important platform actions."""

from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
        verbose_name="操作者",
    )
    action = models.CharField("操作", max_length=100)
    target_type = models.CharField("目标类型", max_length=100, blank=True)
    target_id = models.CharField("目标 ID", max_length=100, blank=True)
    detail = models.JSONField("详细信息", default=dict, blank=True)
    request_id = models.CharField("请求 ID", max_length=32, blank=True)
    ip_address = models.GenericIPAddressField("IP 地址", null=True, blank=True)
    created_at = models.DateTimeField("发生时间", auto_now_add=True)

    class Meta:
        verbose_name = "审计日志"
        verbose_name_plural = "审计日志"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("action", "-created_at")),
            models.Index(fields=("user", "-created_at")),
            models.Index(fields=("target_type", "target_id")),
        ]

    def __str__(self):
        actor = self.user.get_username() if self.user else "system"
        return f"{self.created_at:%Y-%m-%d %H:%M:%S} {actor} {self.action}"
