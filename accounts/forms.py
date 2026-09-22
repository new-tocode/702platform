"""Forms for administrator-provisioned users and member self-service."""

from django import forms
from django.contrib.auth.forms import (
    AdminPasswordChangeForm as DjangoAdminPasswordChangeForm,
    SetPasswordForm,
    UserCreationForm,
    UserChangeForm,
)
from django.utils.translation import gettext_lazy as _

from .models import Profile, User


class AdminUserCreationForm(UserCreationForm):
    """Admin-only account creation form; no public registration uses this form.

    三种评审资格可以建号时直接勾上，省掉「先建号、再进详情页勾一遍」的两步。
    管理员身份不在此列——那是后台的进入权限，建号后再单独确认。
    """

    full_name = forms.CharField(label="姓名", max_length=128, required=True)

    class Meta:
        model = User
        fields = (
            "username",
            "email",
            "is_reviewer",
            "is_preliminary_reviewer",
            "is_super_reviewer",
        )

    def save_profile(self, user):
        Profile.objects.update_or_create(
            user=user,
            defaults={"full_name": self.cleaned_data["full_name"].strip()},
        )

    def save(self, commit=True):
        user = super().save(commit=False)
        user.must_change_password = True
        if commit:
            user.save()
            self.save_profile(user)
        return user


class AdminUserChangeForm(UserChangeForm):
    full_name = forms.CharField(label="姓名", max_length=128, required=False)

    class Meta:
        model = User
        fields = "__all__"
        exclude = ("first_name", "last_name")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        profile = (
            Profile.objects.filter(user_id=self.instance.pk).first()
            if self.instance.pk
            else None
        )
        self.initial["full_name"] = profile.full_name if profile else ""

    def save_profile(self, user):
        Profile.objects.update_or_create(
            user=user,
            defaults={"full_name": self.cleaned_data.get("full_name", "").strip()},
        )

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            self.save_profile(user)
        return user


class AdminPasswordChangeForm(DjangoAdminPasswordChangeForm):
    """Any administrator reset starts a fresh forced-change cycle."""

    def save(self, commit=True):
        user = super().save(commit=False)
        user.must_change_password = True
        if commit:
            user.save()
        return user


class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = (
            "full_name",
            "student_id",
            "college",
            "major",
            "specialty",
            "phone",
            "contact",
        )
        widgets = {
            "full_name": forms.TextInput(attrs={"autocomplete": "name"}),
            "student_id": forms.TextInput(attrs={"autocomplete": "off"}),
            "phone": forms.TelInput(),
        }


class FirstPasswordChangeForm(SetPasswordForm):
    """Form used when the member has not yet replaced an admin-issued password."""


class MemberPasswordChangeForm(forms.Form):
    """Password form for subsequent changes, including the current password."""

    old_password = forms.CharField(
        label=_("当前密码"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )
    new_password1 = forms.CharField(
        label=_("新密码"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    new_password2 = forms.CharField(
        label=_("确认新密码"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_old_password(self):
        old_password = self.cleaned_data["old_password"]
        if not self.user.check_password(old_password):
            raise forms.ValidationError(_("当前密码不正确。"))
        return old_password

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("new_password1")
        password2 = cleaned_data.get("new_password2")
        if password1 and password2 and password1 != password2:
            self.add_error("new_password2", _("两次输入的新密码不一致。"))
        if password1:
            from django.contrib.auth.password_validation import validate_password

            try:
                validate_password(password1, self.user)
            except forms.ValidationError as exc:
                self.add_error("new_password1", exc)
        return cleaned_data

    def save(self):
        self.user.set_password(self.cleaned_data["new_password1"])
        self.user.save(update_fields=["password"])
        return self.user
