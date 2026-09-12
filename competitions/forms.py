"""Forms for administrator-published competitions and registrations."""

from django import forms
from django.contrib.auth import get_user_model

from projects.models import ProjectGroup
from projects.permissions import manageable_group_ids

from .models import CompetitionRegistration
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
    team_leader = forms.ModelChoiceField(
        label="竞赛组长",
        queryset=User.objects.none(),
        help_text="从所选项目组成员中指定，可以是联系人本人。",
    )
    remark = forms.CharField(
        label="备注",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
    )

    def __init__(self, user, competition, instance=None, *args, **kwargs):
        self.user = user
        self.competition = competition
        self.instance = instance
        super().__init__(*args, **kwargs)

        self.available_groups = (
            ProjectGroup.objects.filter(pk__in=manageable_group_ids(user))
            .select_related("leader")
            .order_by("name", "id")
        )
        self.fields["group"].queryset = self.available_groups

        member_queryset = (
            User.objects.filter(project_groups__in=self.available_groups)
            .distinct()
            .select_related("profile")
            .order_by("username")
        )
        self.fields["members"].queryset = member_queryset
        self.fields["team_leader"].queryset = member_queryset

        if instance is not None:
            self.fields["group"].initial = instance.group_id
            self.fields["members"].initial = instance.members.values_list("pk", flat=True)
            self.fields["team_leader"].initial = instance.team_leader_id
            self.fields["remark"].initial = instance.remark
        else:
            # Default the competition team leader to the contact registering it.
            self.fields["team_leader"].initial = user.pk

    def clean(self):
        cleaned_data = super().clean()
        group = cleaned_data.get("group")
        members = cleaned_data.get("members")
        team_leader = cleaned_data.get("team_leader")

        if not self.competition.is_registration_open:
            self.add_error(None, "该竞赛已关闭报名或已超过报名截止时间。")
        if group and not can_register_group(self.user, group):
            self.add_error("group", "你无权为这个项目组登记报名。")

        if group:
            duplicate = CompetitionRegistration.objects.filter(
                competition=self.competition,
                group=group,
            )
            if self.instance is not None:
                duplicate = duplicate.exclude(pk=self.instance.pk)
            if duplicate.exists():
                self.add_error("group", "该项目组已经登记过这场竞赛，不能重复报名。")

        if group and members:
            allowed_ids = set(group.members.values_list("pk", flat=True))
            if any(member.pk not in allowed_ids for member in members):
                self.add_error("members", "参赛成员必须属于所选项目组。")
            if team_leader and team_leader.pk not in allowed_ids:
                self.add_error("team_leader", "竞赛组长必须属于所选项目组。")
            elif team_leader and team_leader.pk not in {member.pk for member in members}:
                self.add_error("team_leader", "竞赛组长必须是参赛成员之一。")
        return cleaned_data


class CompetitionRegistrationAdminForm(forms.ModelForm):
    class Meta:
        model = CompetitionRegistration
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        group = cleaned_data.get("group")
        members = cleaned_data.get("members")
        team_leader = cleaned_data.get("team_leader")
        if group and members:
            allowed_ids = set(group.members.values_list("pk", flat=True))
            if any(member.pk not in allowed_ids for member in members):
                self.add_error("members", "参赛成员必须属于所选项目组。")
            if team_leader and team_leader.pk not in allowed_ids:
                self.add_error("team_leader", "竞赛组长必须属于所选项目组。")
        return cleaned_data
