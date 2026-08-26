"""Account models for administrator-provisioned club members."""

from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.db import models


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
    full_name = models.CharField("姓名", max_length=128, blank=True)
    student_id = models.CharField(
        "学号",
        max_length=64,
        unique=True,
        blank=True,
        null=True,
    )
    college = models.CharField("学院", max_length=128, blank=True)
    major = models.CharField("专业", max_length=128, blank=True)
    phone = models.CharField("手机号", max_length=32, blank=True)
    contact = models.CharField("其他联系方式", max_length=255, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "个人资料"
        verbose_name_plural = "个人资料"
        ordering = ("user__username",)

    def __str__(self):
        return f"{self.user.get_username()} 的个人资料"
