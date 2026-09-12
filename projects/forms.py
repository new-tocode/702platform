"""Forms for member-facing project-group operations."""

from django import forms
from django.contrib.auth import get_user_model

from .models import GroupJoinRequest, ProjectGroup


User = get_user_model()


class GroupJoinRequestForm(forms.ModelForm):
    class Meta:
        model = GroupJoinRequest
        fields = ("message",)
        labels = {"message": "申请理由"}
        widgets = {"message": forms.Textarea(attrs={"rows": 4})}


class GroupDescriptionForm(forms.ModelForm):
    class Meta:
        model = ProjectGroup
        fields = ("description",)
        labels = {"description": "项目组介绍"}
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}


class GroupProposalForm(forms.ModelForm):
    class Meta:
        model = ProjectGroup
        fields = ("proposal",)
        labels = {"proposal": "项目书"}
        help_texts = {"proposal": "支持 doc、docx、pdf，上传后即可提交审核。"}


class ContactTransferForm(forms.Form):
    """Choose the member who becomes the new project-group contact."""

    new_contact = forms.ModelChoiceField(
        label="新联系人",
        queryset=User.objects.none(),
        help_text="只能从当前项目组成员中选择。",
    )

    def __init__(self, group, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.group = group
        self.fields["new_contact"].queryset = (
            group.members.exclude(pk=group.leader_id)
            .select_related("profile")
            .order_by("username")
        )

    def clean_new_contact(self):
        new_contact = self.cleaned_data["new_contact"]
        if not self.group.members.filter(pk=new_contact.pk).exists():
            raise forms.ValidationError("新联系人必须是该项目组成员。")
        return new_contact
