from django import forms
from django.core.exceptions import ValidationError
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from .models import Board, Comment, Post
from .validators import clean_board_name, clean_chinese_board_name


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


class PostForm(forms.ModelForm):
    content = forms.CharField(
        label=_("正文"),
        max_length=20000,
        widget=forms.Textarea(attrs={"rows": 10}),
    )

    class Meta:
        model = Post
        fields = ("title", "content")
        widgets = {"title": forms.TextInput()}

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
