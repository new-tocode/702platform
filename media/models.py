"""Unified image and video media library."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .validators import IMAGE, VIDEO, validate_media_file


class MediaFile(models.Model):
    IMAGE = IMAGE
    VIDEO = VIDEO
    KIND_CHOICES = (
        (IMAGE, "图片"),
        (VIDEO, "视频"),
    )

    file = models.FileField("文件", upload_to="uploads/%Y/%m/")
    kind = models.CharField("媒体类型", max_length=16, choices=KIND_CHOICES)
    caption = models.CharField("说明", max_length=255, blank=True)
    uploader = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploaded_media",
        verbose_name="上传人",
    )
    file_size = models.PositiveBigIntegerField("文件大小", default=0, editable=False)
    created_at = models.DateTimeField("上传时间", auto_now_add=True)

    class Meta:
        verbose_name = "媒体文件"
        verbose_name_plural = "媒体文件"
        ordering = ("-created_at", "-id")

    def __str__(self):
        return self.caption or self.file.name.rsplit("/", 1)[-1]

    def clean(self):
        super().clean()
        if self.file:
            validate_media_file(self.file, self.kind)

    def save(self, *args, **kwargs):
        if self.file:
            self.file_size = self.file.size
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def filename(self):
        return self.file.name.rsplit("/", 1)[-1]

    @property
    def size_in_mb(self):
        return round(self.file_size / (1024 * 1024), 2)
