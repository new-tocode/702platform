"""Public and internal notices published by administrators."""

from django.conf import settings
from django.contrib.auth.models import Group
from django.db import models
from django.utils import timezone

from media.models import MediaFile


class Notice(models.Model):
    PUBLIC = "public"
    INTERNAL = "internal"
    SCOPE_CHOICES = (
        (PUBLIC, "公开"),
        (INTERNAL, "内部"),
    )

    title = models.CharField("标题", max_length=200)
    content = models.TextField("正文")
    scope = models.CharField(
        "可见范围",
        max_length=16,
        choices=SCOPE_CHOICES,
        default=PUBLIC,
    )
    is_pinned = models.BooleanField("置顶", default=False)
    visible_groups = models.ManyToManyField(
        Group,
        blank=True,
        related_name="visible_notices",
        verbose_name="可查看用户组",
        help_text="内部通知必须至少选择一个用户组；属于任一所选用户组的成员可以查看。",
    )
    attachments = models.ManyToManyField(
        MediaFile,
        blank=True,
        related_name="notices",
        verbose_name="配图/视频",
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="published_notices",
        verbose_name="发布人",
    )
    published_at = models.DateTimeField("发布时间", default=timezone.now)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "通知公告"
        verbose_name_plural = "通知公告"
        ordering = ("-is_pinned", "-published_at", "-id")
        indexes = [
            models.Index(fields=("scope", "-published_at")),
            models.Index(fields=("scope", "-is_pinned", "-published_at")),
        ]

    def __str__(self):
        return self.title

    @property
    def is_public(self):
        return self.scope == self.PUBLIC
