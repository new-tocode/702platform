"""成员在历年获奖页上添加记录用的表单。

只收图片，两类各一个多文件字段。视频仍然可以走后台——成员在前台上传一段 500 MB
的视频，页面上既不好看，也没有哪个环节替他把关。
"""

from django import forms
from django.utils import timezone
from django.utils.text import format_lazy
from django.utils.translation import gettext_lazy as _

from core.forms import MultipleFileInput, MultipleImageField

from .models import Award
from .validators import (
    IMAGE_LIMIT,
    MAX_IMAGE_MB,
    validate_certificate,
    validate_photo,
)


#: 年份的下限。历年的获奖记录都是本世纪的事，但留一个宽松的下限用来挡住打错的
#: 五位数年份（20244），比精确到某一年更不容易误伤。
EARLIEST_YEAR = 1900


class AwardForm(forms.ModelForm):
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
        fields = ("title", "competition", "year", "level", "winners", "advisor")
        # 标签必须在这里点名：ModelForm 默认拿模型的 verbose_name 当标签，而那些
        # 中文是给后台看的、不进 .po（见 docs/development.md 的双语范围），照搬过来
        # 就是英文表单上冒出六个中文标签。
        labels = {
            "title": _("奖项名称"),
            "competition": _("赛事名称"),
            "year": _("年份"),
            "level": _("获奖级别"),
            "winners": _("获奖人 / 团队"),
            "advisor": _("指导老师"),
        }
        widgets = {
            "year": forms.NumberInput(attrs={"min": EARLIEST_YEAR}),
            "winners": forms.Textarea(attrs={"rows": 2}),
        }

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

    def award_kwargs(self):
        """交给 ``content.services.create_award`` 的关键字参数。

        表单字段与服务参数一一对应的这份名单写在这里，视图就不必再抄一遍字段名
        ——抄一遍，就多一处改字段时会忘掉的地方。
        """
        return {
            "title": self.cleaned_data["title"],
            "competition": self.cleaned_data["competition"],
            "year": self.cleaned_data["year"],
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
