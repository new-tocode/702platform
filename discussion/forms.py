from django import forms
from django.core.exceptions import ValidationError
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from .models import Board, Comment, Post, PostImage
from .validators import (
    POST_IMAGE_LIMIT,
    clean_board_name,
    clean_chinese_board_name,
    validate_post_image,
)


class BoardForm(forms.ModelForm):
    name_zh = forms.CharField(label=_("中文名称"), max_length=80)

    class Meta:
        model = Board
        fields = ("name_zh", "name")

    def clean_name_zh(self):
        try:
            return clean_chinese_board_name(self.cleaned_data["name_zh"])
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages[0]) from exc

    def clean_name(self):
        name = clean_board_name(self.cleaned_data["name"])
        duplicate = Board.objects.annotate(name_lower=Lower("name")).filter(
            name_lower=name.lower()
        )
        if self.instance.pk:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise forms.ValidationError(_("已有同名板块。"))
        return name


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.FileField):
    widget = MultipleFileInput

    def clean(self, data, initial=None):
        if data in self.empty_values:
            return []
        uploads = data if isinstance(data, (list, tuple)) else [data]
        return [
            super(MultipleImageField, self).clean(upload, initial)
            for upload in uploads
        ]


class PostForm(forms.ModelForm):
    images = MultipleImageField(
        label=_("帖子图片"),
        required=False,
        validators=[validate_post_image],
        help_text=_("最多 3 张，每张不超过 3 MB。"),
        widget=MultipleFileInput(attrs={"accept": "image/*"}),
    )
    content = forms.CharField(
        label=_("正文"),
        max_length=20000,
        widget=forms.Textarea(attrs={"rows": 10}),
    )

    class Meta:
        model = Post
        fields = ("title", "content")
        widgets = {"title": forms.TextInput()}

    def __init__(self, *args, remove_image_ids=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.remove_image_ids = {str(image_id) for image_id in remove_image_ids}

    def clean_title(self):
        title = self.cleaned_data["title"].strip()
        if not title:
            raise forms.ValidationError(_("请输入帖子标题。"))
        return title

    def clean_content(self):
        content = self.cleaned_data["content"].strip()
        if not content:
            raise forms.ValidationError(_("请输入帖子正文。"))
        return content


    def clean_images(self):
        uploads = self.cleaned_data["images"]
        if len(uploads) > POST_IMAGE_LIMIT:
            raise forms.ValidationError(_("每篇帖子最多上传 3 张图片。"))

        if self.instance.pk:
            existing = PostImage.objects.filter(post=self.instance)
            removed = existing.filter(pk__in=self.remove_image_ids).count()
            remaining = existing.count() - removed
        else:
            remaining = 0
        if remaining + len(uploads) > POST_IMAGE_LIMIT:
            raise forms.ValidationError(_("每篇帖子最多保留 3 张图片。"))
        return uploads




class CommentForm(forms.ModelForm):
    content = forms.CharField(
        label=_("评论"),
        max_length=4000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    class Meta:
        model = Comment
        fields = ("content",)

    def clean_content(self):
        content = self.cleaned_data["content"].strip()
        if not content:
            raise forms.ValidationError(_("请输入评论内容。"))
        return content
