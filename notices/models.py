"""Public and internal notices published by administrators."""

from django.conf import settings
from django.contrib.auth.models import Group
from django.db import models
from django.utils import timezone

from media.models import MediaFile


class Notice(models.Model):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONTACTS = "contacts"
    SCOPE_CHOICES = (
        (PUBLIC, "公开"),
        (INTERNAL, "内部"),
        (CONTACTS, "仅联系人可见"),
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
        help_text="仅“内部”通知需要选择用户组；属于任一所选用户组的成员可以查看。“公开”和“仅联系人可见”通知无需选择。",
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


class NoticeRead(models.Model):
    """一条「谁读过哪条通知」的回执，撑着「我的消息」的未读状态。

    未读 = 可见通知（``visibility.member_visible_notices``）减去本表——不物化
    消息副本，所以发布人删除通知后，成员的列表与计数里自然不再出现它；本表随
    通知级联清掉，不留孤儿（迁移里 ``on_delete=CASCADE``）。

    已读是高频、个人、幂等的操作，不写审计（与登录、评审提交不同），只在视图
    里记日志。
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notice_reads",
        verbose_name="用户",
    )
    notice = models.ForeignKey(
        Notice,
        on_delete=models.CASCADE,
        related_name="reads",
        verbose_name="通知",
    )
    read_at = models.DateTimeField("已读时间", default=timezone.now)

    class Meta:
        verbose_name = "通知已读回执"
        verbose_name_plural = "通知已读回执"
        constraints = [
            models.UniqueConstraint(
                fields=("user", "notice"),
                name="unique_notice_read_per_user",
            ),
        ]

    def __str__(self):
        return f"{self.user} → {self.notice}"
