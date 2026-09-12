"""Project groups and their leader/member relationships."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models

from .validators import validate_proposal_file


class ProjectGroup(models.Model):
    name = models.CharField("组名", max_length=200)
    leader = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="led_project_groups",
        verbose_name="项目组联系人",
    )
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="project_groups",
        blank=True,
        verbose_name="成员",
    )
    description = models.TextField("简介", blank=True)
    proposal = models.FileField(
        "项目书",
        upload_to="project_proposals/%Y/%m/",
        blank=True,
        validators=[validate_proposal_file],
        help_text="支持 doc、docx、pdf；由项目组联系人维护，用于提交同行评审。",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "项目组"
        verbose_name_plural = "项目组"
        ordering = ("name", "id")

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # A group's leader is always a member of that group. This keeps the
        # registration form and all membership displays internally consistent.
        if self.leader_id:
            self.members.add(self.leader_id)


class GroupJoinRequest(models.Model):
    """A membership application awaiting review by the group's contact."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    STATUS_CHOICES = (
        (PENDING, "待审核"),
        (APPROVED, "已通过"),
        (REJECTED, "已拒绝"),
    )

    group = models.ForeignKey(
        ProjectGroup,
        on_delete=models.PROTECT,
        related_name="join_requests",
        verbose_name="项目组",
    )
    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="group_join_requests",
        verbose_name="申请人",
    )
    message = models.TextField("申请理由", blank=True)
    status = models.CharField(
        "状态",
        max_length=16,
        choices=STATUS_CHOICES,
        default=PENDING,
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="decided_group_join_requests",
        verbose_name="处理人",
    )
    decided_at = models.DateTimeField("处理时间", null=True, blank=True)
    created_at = models.DateTimeField("提交时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "入组申请"
        verbose_name_plural = "入组申请"
        ordering = ("-created_at", "-id")
        constraints = [
            # At most one pending application per group and applicant; a
            # rejected applicant may apply again later.
            models.UniqueConstraint(
                fields=("group", "applicant"),
                condition=models.Q(status="pending"),
                name="unique_pending_group_join_request",
            ),
        ]
        indexes = [
            models.Index(fields=("group", "status")),
            models.Index(fields=("applicant", "status")),
        ]

    def __str__(self):
        return f"{self.applicant} → {self.group}（{self.get_status_display()}）"


class ProjectContact(get_user_model()):
    """Read-only proxy giving administrators a single list of all contacts.

    Contact identity is derived from ``ProjectGroup.leader``; this proxy stores
    nothing and only exists so the admin can browse every contact at a glance.
    """

    class Meta:
        proxy = True
        verbose_name = "项目组联系人"
        verbose_name_plural = "项目组联系人"
