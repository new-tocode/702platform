"""Account models for administrator-provisioned club members."""

from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _


class UserManager(DjangoUserManager):
    """Keep superuser accounts usable while member accounts require first-login reset."""

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("must_change_password", False)
        return super().create_superuser(
            username,
            email=email,
            password=password,
            **extra_fields,
        )


class User(AbstractUser):
    """Platform user; accounts are created by administrators, not self-signup."""

    must_change_password = models.BooleanField(
        default=True,
        verbose_name="首次登录需改密",
        help_text="管理员发放或重置密码后保持启用，用户成功改密后自动关闭。",
    )
    is_reviewer = models.BooleanField(
        "评审资格",
        default=False,
        help_text="启用后可进入“评审”应用，审阅分配到自己的项目书并给出评审意见。",
    )
    is_preliminary_reviewer = models.BooleanField(
        "初审资格",
        default=False,
        help_text=(
            "启用后可进入“评审”应用，对分配到的送审做初审：初审通过后才会随机分配评审人，"
            "初审打回则本轮不再分配评审人。与“评审资格”相互独立——同时具备时，"
            "本人初审通过的那一轮不会再抽到本人做正式评审。"
        ),
    )
    is_super_reviewer = models.BooleanField(
        "超级评审资格",
        default=False,
        help_text=(
            "启用后可在“评审”中看到全部进行中的评审（含初审中），并对其直接通过或打回："
            "该票单独决定本轮结论，原本等待中的任务（初审一并）随即被释放。"
            "与“评审资格”相互独立——只有同时具备评审资格，才会被随机抽为普通评审人。"
        ),
    )

    objects = UserManager()

    class Meta:
        verbose_name = "用户"
        verbose_name_plural = "用户"


class Profile(models.Model):
    """Member-editable profile fields kept separate from authentication data."""

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
        verbose_name="用户",
    )
    full_name = models.CharField(_("姓名"), max_length=128, blank=True)
    student_id = models.CharField(
        _("学号"),
        max_length=64,
        unique=True,
        blank=True,
        null=True,
    )
    college = models.CharField(_("学院"), max_length=128, blank=True)
    major = models.CharField(_("专业"), max_length=128, blank=True)
    specialty = models.CharField(
        _("特长"),
        max_length=255,
        blank=True,
        help_text=_("可填写多项，用顿号或逗号分隔。"),
    )
    phone = models.CharField(_("手机号"), max_length=32, blank=True)
    contact = models.CharField(_("其他联系方式"), max_length=255, blank=True)
    bio = models.TextField(
        _("个人简介"),
        max_length=1000,
        blank=True,
        help_text=_("最多 1000 字。"),
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "个人资料"
        verbose_name_plural = "个人资料"
        ordering = ("user__username",)

    def __str__(self):
        return f"{self.user.get_username()} 的个人资料"


# --- 后台「身份管理」的四张全局身份名册 -------------------------------------
#
# 身份本身仍是 User 上的布尔字段（is_staff／is_reviewer／…），这里只是换一层
# 皮：让后台能按「身份」而不是按「账号」浏览，一眼看到某个身份上都有谁。
# proxy 不建表、不存数据，也就不存在与布尔字段分叉的第二处真相。
#
# 四张名册都在 accounts 下，后台因此归入「账号与成员」；``config.admin`` 再把
# 它们与项目的两张名册一起提成「身份管理」分组。


class AdminRole(User):
    """身份名册：管理员（``is_staff`` 或 ``is_superuser``）。"""

    class Meta:
        proxy = True
        verbose_name = "管理员"
        verbose_name_plural = "管理员"


class ReviewerRole(User):
    """身份名册：评审人（``is_reviewer``）。"""

    class Meta:
        proxy = True
        verbose_name = "评审人"
        verbose_name_plural = "评审人"


class PreliminaryReviewerRole(User):
    """身份名册：初审人（``is_preliminary_reviewer``）。"""

    class Meta:
        proxy = True
        verbose_name = "初审人"
        verbose_name_plural = "初审人"


class SuperReviewerRole(User):
    """身份名册：超级评审（``is_super_reviewer``）。"""

    class Meta:
        proxy = True
        verbose_name = "超级评审"
        verbose_name_plural = "超级评审"
