"""Forms for administrator-published competitions and registrations."""

from django import forms
from django.contrib.auth import get_user_model

from projects.models import ProjectGroup

from .models import Competition, CompetitionRegistration
from .permissions import can_register_group


User = get_user_model()


class CompetitionRegistrationForm(forms.Form):
    group = forms.ModelChoiceField(label="项目组", queryset=ProjectGroup.objects.none())
    members = forms.ModelMultipleChoiceField(
        label="参赛成员",
        queryset=User.objects.none(),
        widget=forms.SelectMultiple(attrs={"size": 8}),
        help_text="只能选择所选项目组中的成员。",
    )
    remark = forms.CharField(
        label="备注",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
    )

    def __init__(self, user, competition, *args, **kwargs):
        self.user = user
        self.competition = competition
        super().__init__(*args, **kwargs)
        if user.is_staff:
            self.available_groups = ProjectGroup.objects.all()
        else:
            self.available_groups = ProjectGroup.objects.filter(leader=user)
        self.available_groups = self.available_groups.select_related("leader").order_by(
            "name", "id"
        )
        self.fields["group"].queryset = self.available_groups
        self.fields["members"].queryset = (
            User.objects.filter(project_groups__in=self.available_groups)
            .distinct()
            .select_related("profile")
            .order_by("username")
        )

    def clean(self):
        cleaned_data = super().clean()
        group = cleaned_data.get("group")
        members = cleaned_data.get("members")

        if not self.competition.is_registration_open:
            self.add_error(None, "该竞赛已关闭报名或已超过报名截止时间。")
        if group and not can_register_group(self.user, group):
            self.add_error("group", "你无权为这个项目组登记报名。")
        if group and CompetitionRegistration.objects.filter(
            competition=self.competition,
            group=group,
        ).exists():
            self.add_error("group", "该项目组已经登记过这场竞赛，不能重复报名。")
        if group and members:
            allowed_ids = set(group.members.values_list("pk", flat=True))
            invalid_members = [member for member in members if member.pk not in allowed_ids]
            if invalid_members:
                self.add_error("members", "参赛成员必须属于所选项目组。")
        return cleaned_data


class CompetitionRegistrationAdminForm(forms.ModelForm):
    class Meta:
        model = CompetitionRegistration
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        group = cleaned_data.get("group")
        members = cleaned_data.get("members")
        if group and members:
            allowed_ids = set(group.members.values_list("pk", flat=True))
            if any(member.pk not in allowed_ids for member in members):
                self.add_error("members", "参赛成员必须属于所选项目组。")
        return cleaned_data
