"""Public-facing club introduction, awards and member showcase models."""

from django.conf import settings
from django.db import models

from media.models import MediaFile


class ContentPage(models.Model):
    slug = models.SlugField("页面标识", unique=True, max_length=80)
    title = models.CharField("标题", max_length=200)
    content = models.TextField("正文")
    is_published = models.BooleanField("已发布", default=False)
    attachments = models.ManyToManyField(
        MediaFile,
        blank=True,
        related_name="content_pages",
        verbose_name="配图/视频",
    )
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "公开内容页"
        verbose_name_plural = "公开内容页"
        ordering = ("slug",)

    def __str__(self):
        return f"{self.title} ({self.slug})"


class Award(models.Model):
    title = models.CharField("奖项名称", max_length=200)
    competition = models.CharField("赛事名称", max_length=200)
    year = models.PositiveIntegerField("年份")
    level = models.CharField("获奖级别", max_length=100, blank=True)
    winners = models.TextField("获奖人/团队", blank=True)
    attachments = models.ManyToManyField(
        MediaFile,
        blank=True,
        related_name="awards",
        verbose_name="奖状/现场图/视频",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "历年获奖"
        verbose_name_plural = "历年获奖"
        ordering = ("-year", "-created_at", "-id")
        indexes = [models.Index(fields=("-year", "-created_at"))]

    def __str__(self):
        return f"{self.year} {self.title}"


class Showcase(models.Model):
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="showcase_entries",
        verbose_name="成员",
    )
    intro = models.TextField("简介文字", blank=True)
    sort_order = models.IntegerField("排序", default=0)
    is_active = models.BooleanField("启用", default=True)
    photo = models.ForeignKey(
        MediaFile,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="showcases",
        verbose_name="展示照片/视频",
    )

    class Meta:
        verbose_name = "成员风采"
        verbose_name_plural = "成员风采"
        ordering = ("sort_order", "member__username", "-id")
        indexes = [models.Index(fields=("is_active", "sort_order"))]

    def __str__(self):
        return f"{self.member.profile.full_name or self.member.username} 的成员风采"
