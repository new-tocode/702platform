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
from .validators import AVATAR_HELP_TEXT, validate_avatar


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
    """成员自己维护的个人资料。

    字段的**排布**（哪两项并成一行、哪个字段要收窄、谁排在最后）一并声明在这里，
    模板只按 :meth:`rows` 逐格渲染。排布是这张表单自己的事，散进模板就得在那里
    按字段名做判断，字段一动两边都要改。
    """

    #: 一行放两项的字段对；不在此列的字段各占一行，顺序仍看 :attr:`Meta.fields`。
    field_rows = (("full_name", "student_id"), ("college", "major"))
    #: 值短、输入框跟着收窄的字段。
    narrow_fields = ("phone",)

    class Meta:
        model = Profile
        fields = (
            "full_name",
            "student_id",
            "college",
            "major",
            # 手机号排在特长之前：先联系方式，再自述。
            "phone",
            "specialty",
            "contact",
            # 个人简介放最后，且是这张表里唯一的整块文本。
            "bio",
        )
        widgets = {
            "full_name": forms.TextInput(attrs={"autocomplete": "name"}),
            "student_id": forms.TextInput(attrs={"autocomplete": "off"}),
            "phone": forms.TelInput(attrs={"autocomplete": "tel"}),
            "bio": forms.Textarea(attrs={"rows": 8}),
        }

    def rows(self):
        """把字段切成页面上的一行行，供模板逐格渲染。

        每格形如 ``{"field": BoundField, "narrow": bool, "full": bool}``：``narrow``
        是值短、输入框跟着收窄的字段；``full`` 表示这一行只有它一个，横向占满整行
        （特长与个人简介都在此列）。
        """
        paired = {name for row in self.field_rows for name in row}
        rows = [list(row) for row in self.field_rows]
        rows += [[name] for name in self.fields if name not in paired]
        return [
            [
                {
                    "field": self[name],
                    "narrow": name in self.narrow_fields,
                    "full": len(row) == 1,
                }
                for name in row
            ]
            for row in rows
        ]


class AvatarForm(forms.Form):
    """上传或更换头像。

    刻意不是 ModelForm：后者在校验通过的那一刻就把上传文件写进了实例，
    服务层再想读「原来的头像叫什么」已经读不到了（换头像要顺手删掉旧文件）。
    这里只收一张图，写库由 ``accounts.services.set_avatar`` 一处完成。
    """

    avatar = forms.ImageField(
        label=_("头像"),
        widget=forms.FileInput(),
        validators=[validate_avatar],
        help_text=AVATAR_HELP_TEXT,
        error_messages={"required": _("请选择要上传的图片。")},
    )


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
