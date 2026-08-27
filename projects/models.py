"""Project groups and their leader/member relationships."""

from django.conf import settings
from django.db import models


class ProjectGroup(models.Model):
    name = models.CharField("组名", max_length=200)
    leader = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="led_project_groups",
        verbose_name="组长",
    )
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="project_groups",
        blank=True,
        verbose_name="成员",
    )
    description = models.TextField("简介", blank=True)
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
