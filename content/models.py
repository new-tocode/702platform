"""Public-facing club introduction, awards and member showcase models."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from media.models import MediaFile

from . import tier_rules


class ContentPage(models.Model):
    slug = models.SlugField("页面标识", unique=True, max_length=80)
    title = models.CharField("标题", max_length=200)
    content = models.TextField("正文", max_length=20000)
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


#: 获奖层级。取值是存储码，标签是惰性的——后台与前台共用这一份，英文界面上不能
#: 冒中文（与 `reviews.models.REVIEW_TYPE_CHOICES` 同一写法）。码值定义在
#: `tier_rules`：那边的折叠与推断要用同一套码，两边必须是同一个来源。
AWARD_TIER_CHOICES = (
    (tier_rules.NATIONAL, _("国家级")),
    (tier_rules.PROVINCIAL, _("省级")),
    (tier_rules.SCHOOL, _("校级")),
)


class Award(models.Model):
    title = models.CharField("奖项名称", max_length=200)
    competition = models.CharField("赛事名称", max_length=200)
    year = models.PositiveIntegerField("年份")
    # 层级是判重身份的一部分（见 content/similarity.py）：同一年、同一赛事、同一批
    # 获奖人下，每个层级只允许一条记录——「省一等奖」与「东北赛区一等奖」是同一层，
    # 不该录成两条。证书上的具体写法仍旧放进 level，只作展示与搜索。
    #
    # 老记录里可能有空值（回填时认不出层级的），判重按「没填就不比这一项」处理，
    # 与其余字段同一条规矩；后台改一次就会被要求补上。
    tier = models.CharField("获奖层级", max_length=20, choices=AWARD_TIER_CHOICES)
    # 级别与获奖人都是必填：级别填证书上的原话，供展示与搜索（判重不看它，看的是
    # 上面的 tier）；获奖人是「我的获奖」按姓名搜索所依附的那一项，空着那件事就做
    # 不成。指导老师仍然可空。
    level = models.CharField("证书上的级别写法", max_length=100)
    winners = models.TextField("获奖人/团队", max_length=500)
    advisor = models.CharField("指导老师", max_length=200, blank=True)
    # 附件按用途分成两类，因为它们后来的去处不同：证书要能勾选打包下载，参赛图
    # 只在页面上看。原先只有一个 attachments，两者混在一起，下载时挑不出来。
    certificates = models.ManyToManyField(
        MediaFile,
        blank=True,
        related_name="certificate_awards",
        verbose_name="获奖证书",
        # 证书只收图片：打包下载会把它们整个读进内存再压，一段 500 MB 的视频
        # 不该混进来。视频仍然是「参赛图片」那边合法的一员。
        limit_choices_to={"kind": MediaFile.IMAGE},
    )
    photos = models.ManyToManyField(
        MediaFile,
        blank=True,
        related_name="photo_awards",
        verbose_name="参赛图片",
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
    intro = models.TextField("简介文字", blank=True, max_length=1000)
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


class HomeSlide(models.Model):
    """首页影像滚动区的一张图，由管理员在后台挑选与排序。

    图片来自共享媒体库；这里只挑已有的 MediaFile，不复制文件。限定为图片类型，
    视频在横向滚动条里既不好看也不好操作。
    """

    image = models.ForeignKey(
        MediaFile,
        on_delete=models.PROTECT,
        limit_choices_to={"kind": MediaFile.IMAGE},
        related_name="home_slides",
        verbose_name="图片",
    )
    title = models.CharField("说明文字", max_length=120, blank=True)
    sort_order = models.IntegerField("排序", default=0)
    is_active = models.BooleanField("启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "首页轮播"
        verbose_name_plural = "首页轮播"
        ordering = ("sort_order", "pk")
        indexes = [models.Index(fields=("is_active", "sort_order"))]

    def __str__(self):
        return self.title or self.image.caption or f"轮播图 #{self.pk}"

    def clean(self):
        super().clean()
        if self.image_id and self.image.kind != MediaFile.IMAGE:
            raise ValidationError({"image": "首页轮播只支持图片，不支持视频。"})
