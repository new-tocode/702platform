"""Building blocks for the review tests: users, project groups and uploads.

These are the nouns every test module needs, spelled once. Nothing here asserts
anything and nothing here touches a URL — a factory creates the object it
returns and stops.
"""

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile

from projects.models import ProjectGroup


User = get_user_model()

#: 所有测试账号共用的密码；需要真正走登录流程的用例（如登录提醒）用它。
DEFAULT_PASSWORD = "Password-123!"

#: 项目资料内容无关紧要，只要是能通过校验的 zip 即可（开头四个字节是 zip 的文件头）。
MATERIALS_BYTES = b"PK\x03\x04test materials"


def qualify(user, **flags):
    """Give an existing account qualifications, and switch off the forced reset.

    ``must_change_password`` is cleared because most tests never go through the
    forced-change redirect; the ones that care set it back themselves.
    """
    for name, value in flags.items():
        setattr(user, name, value)
    user.must_change_password = False
    user.save(update_fields=[*flags, "must_change_password"])
    return user


def make_user(username, **flags):
    """An account with the given flags (``is_reviewer`` 等) and no forced reset."""
    return qualify(
        User.objects.create_user(username=username, password=DEFAULT_PASSWORD), **flags
    )


def make_reviewer(username, **flags):
    """Holds 评审资格。"""
    return make_user(username, is_reviewer=True, **flags)


def make_preliminary_reviewer(username, **flags):
    """Holds 初审资格。"""
    return make_user(username, is_preliminary_reviewer=True, **flags)


def make_super_reviewer(username, **flags):
    """Holds 超级评审资格（默认不再给评审资格，模拟只有一票敲定权的账号）。"""
    return make_user(username, is_super_reviewer=True, **flags)


def make_admin(username, **flags):
    """A 后台管理员。superuser 自带全部模型权限，可以直接改派与删整轮。"""
    return User.objects.create_superuser(
        username=username, password=DEFAULT_PASSWORD, **flags
    )


def make_group(name, *, leader, members=(), write_materials=True):
    """A project group with its materials attached.

    ``write_materials=False`` 只记下项目资料的文件名、不写字节：给那些只需要
    「这个组有项目资料」这个事实、从不读它的用例（送审要求项目资料存在，但不校验内容）。
    """
    group = ProjectGroup.objects.create(name=name, leader=leader)
    if members:
        group.members.add(*members)
    if write_materials:
        group.materials.save("materials.zip", ContentFile(MATERIALS_BYTES), save=True)
    else:
        group.materials.name = "project_proposals/existing.zip"
        group.save(update_fields=["materials"])
    return group


def materials_upload(name="reply.zip"):
    """A file that passes the reply validator (zip, non-empty)."""
    return SimpleUploadedFile(name, MATERIALS_BYTES, content_type="application/zip")
