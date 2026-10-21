"""成员在前台录入社团成果用的表单：获奖、论文、专利。

获奖表单只收图片，两类各一个多文件字段；论文与专利只登记文字信息（论文原文与
专利证书的版权/分发口径不在平台手里）。视频仍然可以走后台——成员在前台上传一段
500 MB 的视频，页面上既不好看，也没有哪个环节替他把关。
"""

from django import forms
from django.utils import timezone
from django.utils.text import format_lazy
from django.utils.translation import gettext_lazy as _

from core.forms import MultipleFileInput, MultipleImageField

from .models import AcademicPaper, Award, Patent
from .selectors import find_duplicate_paper
from .validators import (
    IMAGE_LIMIT,
    MAX_IMAGE_MB,
    validate_certificate,
    validate_photo,
)


#: 年份的下限。历年的成果记录都是本世纪的事，但留一个宽松的下限用来挡住打错的
#: 五位数年份（20244），比精确到某一年更不容易误伤。
EARLIEST_YEAR = 1900


class AchievementFormMixin:
    """三张成果表单共用的两件事：年份默认今年、年份范围校验。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 年份默认填今年：绝大多数记录是当年的，省一次输入。
        if not self.instance.pk and not self.is_bound:
            self.fields["year"].initial = timezone.localdate().year

    def clean_year(self):
        year = self.cleaned_data["year"]
        latest = timezone.localdate().year + 1
        if not EARLIEST_YEAR <= year <= latest:
            raise forms.ValidationError(
                _("年份需在 %(earliest)s 到 %(latest)s 之间。")
                % {"earliest": EARLIEST_YEAR, "latest": latest}
            )
        return year


class AwardForm(AchievementFormMixin, forms.ModelForm):
    # 提示语里的数字用 format_lazy 填，不能用 `_("…%(limit)s…") % {...}`：惰性译文的
    # `%` 会在**导入那一刻**求值，那会儿语言还是中文，字符串就此定型，英文界面上永远
    # 是中文。format_lazy 把这次求值推迟到渲染时。
    certificates = MultipleImageField(
        label=_("获奖证书"),
        required=False,
        validators=[validate_certificate],
        help_text=format_lazy(
            _("最多 {limit} 张，每张不超过 {mb} MB；可打包下载。"),
            limit=IMAGE_LIMIT,
            mb=MAX_IMAGE_MB,
        ),
        widget=MultipleFileInput(attrs={"accept": "image/*"}),
    )
    photos = MultipleImageField(
        label=_("参赛图片"),
        required=False,
        validators=[validate_photo],
        help_text=format_lazy(
            _("最多 {limit} 张，每张不超过 {mb} MB。"),
            limit=IMAGE_LIMIT,
            mb=MAX_IMAGE_MB,
        ),
        widget=MultipleFileInput(attrs={"accept": "image/*"}),
    )

    class Meta:
        model = Award
        fields = ("title", "competition", "year", "tier", "level", "winners", "advisor")
        # 标签必须在这里点名：ModelForm 默认拿模型的 verbose_name 当标签，而那些
        # 中文是给后台看的、不进 .po（见 AGENTS.md §4 的双语范围），照搬过来
        # 就是英文表单上冒出一片中文标签。`tier` 的选项标签不在这里——它来自模型上
        # 那份惰性 choices（见 models.AWARD_TIER_CHOICES），与标签同样是可译的。
        labels = {
            "title": _("奖项名称"),
            "competition": _("赛事名称"),
            "year": _("年份"),
            "tier": _("获奖层级"),
            "level": _("证书上的级别写法"),
            "winners": _("获奖人 / 团队"),
            "advisor": _("指导老师"),
        }
        widgets = {
            "year": forms.NumberInput(attrs={"min": EARLIEST_YEAR}),
            "winners": forms.Textarea(attrs={"rows": 2}),
        }

    def award_kwargs(self):
        """交给 ``content.services.create_award`` 的关键字参数。

        表单字段与服务参数一一对应的这份名单写在这里，视图就不必再抄一遍字段名
        ——抄一遍，就多一处改字段时会忘掉的地方。
        """
        return {
            "title": self.cleaned_data["title"],
            "competition": self.cleaned_data["competition"],
            "year": self.cleaned_data["year"],
            "tier": self.cleaned_data["tier"],
            "level": self.cleaned_data["level"],
            "winners": self.cleaned_data["winners"],
            "advisor": self.cleaned_data["advisor"],
            "certificates": self.cleaned_data["certificates"],
            "photos": self.cleaned_data["photos"],
        }

    def clean_certificates(self):
        return self._check_count(self.cleaned_data["certificates"])

    def clean_photos(self):
        return self._check_count(self.cleaned_data["photos"])

    def _check_count(self, uploads):
        if len(uploads) > IMAGE_LIMIT:
            raise forms.ValidationError(
                _("最多上传 %(limit)s 张，这次选了 %(count)s 张。")
                % {"limit": IMAGE_LIMIT, "count": len(uploads)}
            )
        return uploads


class PaperForm(AchievementFormMixin, forms.ModelForm):
    """成员登记一篇学术论文。"""

    class Meta:
        model = AcademicPaper
        fields = (
            "title",
            "authors",
            "venue",
            "year",
            "paper_type",
            "indexing",
            "doi",
            "abstract",
        )
        # 与 AwardForm 同一规矩：标签在表单里点名，模型上的中文只给后台看。
        # 下拉选项来自模型那份惰性 choices，不在这里重复。
        labels = {
            "title": _("论文题目"),
            "authors": _("论文作者"),
            "venue": _("期刊 / 会议"),
            "year": _("年份"),
            "paper_type": _("论文类型"),
            "indexing": _("收录情况"),
            "doi": _("DOI / 原文链接"),
            "abstract": _("摘要"),
        }
        widgets = {
            "year": forms.NumberInput(attrs={"min": EARLIEST_YEAR}),
            "authors": forms.Textarea(attrs={"rows": 2}),
            "abstract": forms.Textarea(attrs={"rows": 6}),
        }

    def clean(self):
        """同一年里，题目与作者都相同的论文只留一条。

        比的是去掉空白、标点并压平大小写后的串（``tier_rules.normalize``），不是
        pg_trgm 相似度：论文的题目与作者都是人一条条录的，错别字该由录入的人自己
        发现，而「同一篇又录了一遍」用整串相同就能拦住。数据库上没有唯一约束；
        并发双击由 ``services.create_paper`` 在咨询锁里再查一次兜底，绕过那两处
        的 ORM 写入仍可能重复。
        """
        cleaned = super().clean()
        title = cleaned.get("title")
        authors = cleaned.get("authors")
        year = cleaned.get("year")
        if not (title and authors and year):
            return cleaned

        existing = find_duplicate_paper(
            title=title,
            authors=authors,
            year=year,
            exclude_pk=self.instance.pk or None,
        )
        if existing is not None:
            raise forms.ValidationError(
                _("已经登记过同一篇论文（题目、作者与年份相同）。")
            )
        return cleaned

    def paper_kwargs(self):
        """交给 ``content.services.create_paper`` 的关键字参数。"""
        return {
            "title": self.cleaned_data["title"],
            "authors": self.cleaned_data["authors"],
            "venue": self.cleaned_data["venue"],
            "year": self.cleaned_data["year"],
            "paper_type": self.cleaned_data["paper_type"],
            "indexing": self.cleaned_data["indexing"],
            "doi": self.cleaned_data["doi"],
            "abstract": self.cleaned_data["abstract"],
        }


class PatentForm(AchievementFormMixin, forms.ModelForm):
    """成员登记一项专利。"""

    class Meta:
        model = Patent
        fields = (
            "title",
            "inventors",
            "patent_number",
            "year",
            "patent_type",
            "status",
            "summary",
        )
        labels = {
            "title": _("专利名称"),
            "inventors": _("发明人"),
            "patent_number": _("专利号 / 申请号"),
            "year": _("年份"),
            "patent_type": _("专利类型"),
            "status": _("当前状态"),
            "summary": _("简介"),
        }
        widgets = {
            "year": forms.NumberInput(attrs={"min": EARLIEST_YEAR}),
            "inventors": forms.Textarea(attrs={"rows": 2}),
            "summary": forms.Textarea(attrs={"rows": 5}),
        }

    def clean_patent_number(self):
        """专利号去空白后大小写不敏感地查重。

        数据库上有同名唯一约束（见 ``Patent.Meta.constraints``），这里先给出一句
        能读懂的提示；约束是并发提交时的最后一道兜底。
        """
        value = "".join(self.cleaned_data["patent_number"].split())
        duplicates = Patent.objects.filter(patent_number__iexact=value)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError(_("这个专利号已经登记过了。"))
        return value
