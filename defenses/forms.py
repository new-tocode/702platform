"""成员侧表单：答辩申请正文与讨论评论。"""

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import (
    DEFENSE_COMMENT_MAX_CHARS,
    DEFENSE_CONTENT_MAX_CHARS,
    DefenseComment,
    DefenseRequest,
)


class DefenseRequestForm(forms.ModelForm):
    """申请／修改答辩安排。提示文案由模型的 ``help_text`` 带出。"""

    class Meta:
        model = DefenseRequest
        fields = ("content",)
        labels = {"content": _("答辩安排")}
        widgets = {"content": forms.Textarea(attrs={"rows": 8})}


class DefenseCommentForm(forms.ModelForm):
    """一条评论。``body`` 必须显式声明：模型上它允许为空（编辑留痕不写正文）。"""

    body = forms.CharField(
        label=_("评论"),
        max_length=DEFENSE_COMMENT_MAX_CHARS,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    class Meta:
        model = DefenseComment
        fields = ("body",)
        labels = {"body": _("评论")}

    def clean_body(self):
        body = self.cleaned_data["body"].strip()
        if not body:
            raise forms.ValidationError(_("评论内容不能为空。"))
        return body
