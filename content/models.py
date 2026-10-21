"""Public-facing club introduction, achievements and member showcase models."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
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


#: 论文类型与收录情况。标签是惰性的：后台与前台共用这一份 choices，英文前台
#: 不能冒出中文（与 ``AWARD_TIER_CHOICES`` 同一写法）。
PAPER_TYPE_CHOICES = (
    ("journal", _("期刊论文")),
    ("conference", _("会议论文")),
)

PAPER_INDEXING_CHOICES = (
    ("sci", _("SCI / EI")),
    ("core", _("中文核心")),
    ("other", _("其他收录")),
    ("none", _("未收录")),
)


class AcademicPaper(models.Model):
    """社团成员公开发表的学术论文。

    只登记书目信息，不收 PDF：论文原文的版权与分发口径不在平台手里，公开页给一个
    DOI／原文链接就够了。与 ``Award`` 一样由成员在前台录入、管理员在后台维护。
    """

    title = models.CharField("论文题目", max_length=300)
    authors = models.TextField("作者", max_length=500)
    venue = models.CharField("期刊 / 会议", max_length=200)
    year = models.PositiveIntegerField("年份")
    paper_type = models.CharField(
        "论文类型", max_length=20, choices=PAPER_TYPE_CHOICES
    )
    # 收录情况可不填：不是每篇论文都有索引，也不该逼人把「未收录」当成一条信息。
    indexing = models.CharField(
        "收录情况", max_length=20, choices=PAPER_INDEXING_CHOICES, blank=True
    )
    # 可以填 DOI（10.xxxx/…），也可以直接填原文地址；展示时由 external_url 统一。
    doi = models.CharField("DOI / 原文链接", max_length=300, blank=True)
    abstract = models.TextField("摘要", max_length=2000, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "学术论文"
        verbose_name_plural = "学术论文"
        ordering = ("-year", "-created_at", "-id")
        indexes = [models.Index(fields=("-year", "-created_at"))]

    def __str__(self):
        return f"{self.year} {self.title}"

    @property
    def external_url(self):
        """把 DOI 或原文地址变成一个可点的链接；空值返回空串。

        只认 http(s) 与 DOI 前缀：别的写法（例如 ``javascript:``）一律落到 DOI
        解析器上，模板因此不需要再做一层「这个链接能不能点」的判断。
        """
        value = (self.doi or "").strip()
        if not value:
            return ""
        lowered = value.lower()
        if lowered.startswith(("http://", "https://")):
            return value
        if lowered.startswith("doi:"):
            value = value[4:].strip()
        return f"https://doi.org/{value}"


#: 专利类型与当前状态。区块名叫「发明专利」，但队里真正拿到的可能是实用新型
#: 或外观设计，类型仍要如实可分。
PATENT_TYPE_CHOICES = (
    ("invention", _("发明专利")),
    ("utility", _("实用新型")),
    ("design", _("外观设计")),
)

PATENT_STATUS_CHOICES = (
    ("granted", _("已授权")),
    ("reviewing", _("审查中")),
    ("applied", _("已申请")),
)


class Patent(models.Model):
    """社团成员取得或正在申请中的专利。

    专利号是这条记录的身份：同号只允许一条（库里有大小写不敏感的唯一约束）。
    状态允许「审查中／已申请」——成果页展示的是社团的技术积累，不必等到授权。
    """

    title = models.CharField("专利名称", max_length=300)
    inventors = models.TextField("发明人", max_length=500)
    patent_number = models.CharField("专利号 / 申请号", max_length=100)
    year = models.PositiveIntegerField("年份")
    patent_type = models.CharField(
        "专利类型", max_length=20, choices=PATENT_TYPE_CHOICES
    )
    status = models.CharField("当前状态", max_length=20, choices=PATENT_STATUS_CHOICES)
    summary = models.TextField("简介", max_length=2000, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "发明专利"
        verbose_name_plural = "发明专利"
        ordering = ("-year", "-created_at", "-id")
        indexes = [models.Index(fields=("-year", "-created_at"))]
        constraints = [
            # 大小写不敏感：``CN123`` 与 ``cn123`` 是同一个专利号。数据库这一道是
            # 兜底，前台表单另有更早、更好读的提示（见 ``content.forms``）。
            models.UniqueConstraint(
                Lower("patent_number"),
                name="content_patent_number_ci_unique",
            ),
        ]

    def __str__(self):
        return f"{self.year} {self.title}"

    def clean(self):
        """专利号去掉空白后再交给唯一约束比较。

        表单路径已经去过一次；后台与 `full_clean()` 也走这里，``CN 123`` 与
        ``CN123`` 在保存前先变成同一个串。``save()`` 不调用 `full_clean()`，
        `objects.create()` / `bulk_create()` 仍可绕过——那是已声明的限制。
        """
        super().clean()
        self.patent_number = "".join((self.patent_number or "").split())


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
