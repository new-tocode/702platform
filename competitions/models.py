"""Competition announcements and project-group registrations."""

from django.conf import settings
from django.db import models
from django.utils import timezone

from projects.models import ProjectGroup


class Competition(models.Model):
    title = models.CharField("竞赛名称", max_length=200)
    description = models.TextField("竞赛说明")
    deadline = models.DateTimeField("报名截止时间")
    team_size = models.CharField(
        "组队人数要求",
        max_length=100,
        blank=True,
        help_text="例如：2-5 人；仅作展示说明，具体成员由报名时选择。",
    )
    is_open = models.BooleanField("报名开放", default=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="published_competitions",
        verbose_name="发布人",
    )
    published_at = models.DateTimeField("发布时间", default=timezone.now)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "竞赛信息"
        verbose_name_plural = "竞赛信息"
        ordering = ("-is_open", "deadline", "-published_at", "-id")
        indexes = [
            models.Index(fields=("is_open", "deadline")),
            models.Index(fields=("-published_at",)),
        ]

    def __str__(self):
        return self.title

    @property
    def is_registration_open(self):
        return self.is_open and timezone.now() <= self.deadline


class CompetitionRegistration(models.Model):
    competition = models.ForeignKey(
        Competition,
        on_delete=models.PROTECT,
        related_name="registrations",
        verbose_name="竞赛",
    )
    group = models.ForeignKey(
        ProjectGroup,
        on_delete=models.PROTECT,
        related_name="competition_registrations",
        verbose_name="项目组",
    )
    registered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="competition_registrations_created",
        verbose_name="登记人",
    )
    team_leader = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="led_competition_registrations",
        verbose_name="竞赛组长",
        help_text="由联系人在所选项目组成员中指定，可以是联系人本人。",
    )
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="competition_registrations",
        verbose_name="参赛成员",
    )
    remark = models.TextField("备注", blank=True)
    created_at = models.DateTimeField("登记时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "竞赛报名"
        verbose_name_plural = "竞赛报名"
        ordering = ("-created_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("competition", "group"),
                name="unique_competition_group_registration",
            ),
        ]

    def __str__(self):
        return f"{self.group} - {self.competition}"
