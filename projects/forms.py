"""Forms for member-facing project-group operations."""

from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from .models import (
    MAX_ADVISORS_PER_GROUP,
    GroupCreateRequest,
    GroupJoinRequest,
    ProjectGroup,
)


User = get_user_model()


class GroupJoinRequestForm(forms.ModelForm):
    class Meta:
        model = GroupJoinRequest
        fields = ("message",)
        labels = {"message": _("申请理由")}
        widgets = {"message": forms.Textarea(attrs={"rows": 4})}


class GroupCreateRequestForm(forms.ModelForm):
    """申请创建项目组：名称与描述必填，其余（学院、指导老师）可先不填。"""

    class Meta:
        model = GroupCreateRequest
        fields = (
            "name",
            "description",
            "college",
            "advisor_1",
            "advisor_2",
            "advisor_3",
        )
        labels = {
            "name": _("项目组名称"),
            "description": _("项目组描述"),
            "college": _("学院（选填）"),
            "advisor_1": _("指导老师 1（选填）"),
            "advisor_2": _("指导老师 2（选填）"),
            "advisor_3": _("指导老师 3（选填）"),
        }
        widgets = {"description": forms.Textarea(attrs={"rows": 5})}

    def advisor_names(self):
        """按槽位顺序返回已填写的指导老师姓名；空槽位不占位，不留空洞。"""
        return [
            self.cleaned_data[f"advisor_{slot}"].strip()
            for slot in range(1, MAX_ADVISORS_PER_GROUP + 1)
            if self.cleaned_data.get(f"advisor_{slot}", "").strip()
        ]


class GroupDescriptionForm(forms.ModelForm):
    class Meta:
        model = ProjectGroup
        fields = ("description",)
        labels = {"description": _("项目组介绍")}
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}


class GroupInfoForm(forms.ModelForm):
    """学院的填写，外加指导老师的三个槽位。

    指导老师存成独立的 ``ProjectAdvisor`` 行，但界面上是固定的三行输入框——
    上限就是 3 位，固定槽位比可增删的表单集更直观，空槽位即表示这一位不存在。
    """

    advisor_1 = forms.CharField(label=_("指导老师 1"), max_length=128, required=False)
    advisor_2 = forms.CharField(label=_("指导老师 2"), max_length=128, required=False)
    advisor_3 = forms.CharField(label=_("指导老师 3"), max_length=128, required=False)

    class Meta:
        model = ProjectGroup
        fields = ("college",)
        labels = {"college": _("学院")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            return
        advisors = list(self.instance.advisors.all()[:MAX_ADVISORS_PER_GROUP])
        for index, advisor in enumerate(advisors, start=1):
            self.fields[f"advisor_{index}"].initial = advisor.name

    def advisor_names(self):
        """按槽位顺序返回已填写的姓名；空槽位不占位，不留空洞。"""
        return [
            self.cleaned_data[f"advisor_{index}"].strip()
            for index in range(1, MAX_ADVISORS_PER_GROUP + 1)
            if self.cleaned_data.get(f"advisor_{index}", "").strip()
        ]


class GroupProposalForm(forms.ModelForm):
    class Meta:
        model = ProjectGroup
        fields = ("proposal",)
        labels = {"proposal": _("项目书")}
        help_texts = {"proposal": _("支持 doc、docx、pdf，上传后即可提交审核。")}


class ContactTransferForm(forms.Form):
    """Choose the member who becomes the new project-group contact."""

    new_contact = forms.ModelChoiceField(
        label=_("新联系人"),
        queryset=User.objects.none(),
        help_text=_("只能从当前项目组成员中选择。"),
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
            raise forms.ValidationError(_("新联系人必须是该项目组成员。"))
        return new_contact
