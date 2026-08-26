from django import forms

from .models import Notice


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
        if scope == Notice.PUBLIC and visible_groups:
            self.add_error(
                "visible_groups",
                "公开通知不需要选择可查看用户组。",
            )
        return cleaned_data
