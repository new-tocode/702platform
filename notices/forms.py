"""通知公告与私信的表单。

公告那张只服务后台；私信这张是成员用的，标签一律经 gettext（见
``../docs/术语表.md`` 的「惰性译文」）。
"""

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import DirectMessage, Notice


class NoticeAdminForm(forms.ModelForm):
    class Meta:
        model = Notice
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        scope = cleaned_data.get("scope")
        visible_groups = cleaned_data.get("visible_groups")
        if scope == Notice.INTERNAL and not visible_groups:
            self.add_error(
                "visible_groups",
                "内部通知必须至少选择一个可查看用户组。",
            )
        if scope in (Notice.PUBLIC, Notice.CONTACTS) and visible_groups:
            self.add_error(
                "visible_groups",
                "只有内部通知才需要选择可查看用户组。",
            )
        return cleaned_data


class DirectMessageForm(forms.ModelForm):
    """写一条私信：只有一个正文字段。

    标签、上限与帮助文字都不在这里写第二遍——字段原样取自 ``DirectMessage``
    （``max_length`` 也由它带到 textarea 的 ``maxlength`` 上），所以「约 1500 字」
    只有 ``models.DIRECT_MESSAGE_MAX_CHARS`` 一处。这里只补一句空正文的提示：
    默认那句是「这个字段是必填项。」，对「写私信」这个动作不够具体。
    两边都留白时提示哪一句，见 ``Meta.error_messages``。
    """

    class Meta:
        model = DirectMessage
        fields = ("body",)
        labels = {"body": _("私信内容")}
        widgets = {"body": forms.Textarea(attrs={"rows": 6})}
        error_messages = {"body": {"required": _("请输入私信内容。")}}
