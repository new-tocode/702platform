"""Journal-style peer review of project proposals.

Each :class:`ProjectSubmission` is one review round of a project group's
proposal; :class:`ReviewAssignment` records one reviewer's verdict. A submission
is approved only when every assignment is complete and every verdict approves.

The proposal itself is **not** copied here: reviewers download the project
group's current proposal (``ProjectGroup.proposal``) from the group detail page,
so there is a single stored file per group.
"""

from django.conf import settings
from django.db import models

from projects.models import ProjectGroup


class ProjectSubmission(models.Model):
    PENDING = "pending"
    APPROVED = "approved"
    NEEDS_REVISION = "needs_revision"
    STATUS_CHOICES = (
        (PENDING, "评审中"),
        (APPROVED, "已通过"),
        (NEEDS_REVISION, "需修改"),
    )

    group = models.ForeignKey(
        ProjectGroup,
        on_delete=models.PROTECT,
        related_name="submissions",
        verbose_name="项目组",
    )
    round = models.PositiveIntegerField("评审轮次", default=1)
    message = models.TextField("提交说明", blank=True)
    status = models.CharField(
        "状态",
        max_length=20,
        choices=STATUS_CHOICES,
        default=PENDING,
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="project_submissions",
        verbose_name="提交人",
    )
    submitted_at = models.DateTimeField("提交时间", auto_now_add=True)
    decided_at = models.DateTimeField("完成时间", null=True, blank=True)

    class Meta:
        verbose_name = "项目书送审"
        verbose_name_plural = "项目书送审"
        ordering = ("-submitted_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("group", "round"),
                name="unique_group_submission_round",
            ),
        ]
        indexes = [
            models.Index(fields=("group", "status")),
            models.Index(fields=("status", "-submitted_at")),
        ]

    def __str__(self):
        return f"{self.group} 第 {self.round} 轮送审"

    @property
    def is_approved(self):
        return self.status == self.APPROVED

    @property
    def pending_count(self):
        return self.assignments.filter(status=ReviewAssignment.PENDING).count()


class ReviewAssignment(models.Model):
    PENDING = "pending"
    COMPLETED = "completed"
    STATUS_CHOICES = (
        (PENDING, "待评审"),
        (COMPLETED, "已完成"),
    )

    APPROVE = "approve"
    REVISE = "revise"
    DECISION_CHOICES = (
        (APPROVE, "通过"),
        (REVISE, "需修改"),
    )

    submission = models.ForeignKey(
        ProjectSubmission,
        on_delete=models.CASCADE,
        related_name="assignments",
        verbose_name="送审",
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="review_assignments",
        verbose_name="评审人",
    )
    status = models.CharField(
        "状态",
        max_length=16,
        choices=STATUS_CHOICES,
        default=PENDING,
    )
    decision = models.CharField(
        "评审决定",
        max_length=16,
        choices=DECISION_CHOICES,
        blank=True,
    )
    comment = models.TextField("评审意见", blank=True)
    assigned_at = models.DateTimeField("分配时间", auto_now_add=True)
    completed_at = models.DateTimeField("完成时间", null=True, blank=True)

    class Meta:
        verbose_name = "评审任务"
        verbose_name_plural = "评审任务"
        ordering = ("status", "-assigned_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("submission", "reviewer"),
                name="unique_submission_reviewer",
            ),
        ]
        indexes = [
            models.Index(fields=("reviewer", "status")),
        ]

    def __str__(self):
        return f"{self.reviewer} 评审 {self.submission}"

    @property
    def is_completed(self):
        return self.status == self.COMPLETED
