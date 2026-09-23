"""账号相关的写操作。

两件事：后台批量授予／撤销评审资格，以及个人主页上的头像。前者要事务、要审计，
所以不写在 admin 里——那里过去改资格连审计都不留。

头像的写入口也收在这里，而不是散进视图：换头像除了写字段，还要把旧文件从
磁盘上删掉，两件事得挨着做，而且不该让视图去碰存储层。
"""

from django.db import transaction

from core.audit import record_audit

from .models import User


#: 允许批量改的资格字段。
#:
#: 刻意不含 ``is_superuser`` 与 ``is_active``：那两个是账号本身的状态，
#: 该在用户编辑页逐个确认，被一次批量动作改掉太危险。
QUALIFICATION_FLAGS = ("is_reviewer", "is_preliminary_reviewer", "is_super_reviewer")


def set_qualification(*, users, flag, value, actor, request=None):
    """批量授予或撤销一项评审资格，返回真正发生变化的账号数。

    ``flag`` 是 ``accounts.User`` 上的布尔字段名，只接受
    :data:`QUALIFICATION_FLAGS` 里的那几个。取值已经相同的账号会被跳过，
    所以重复提交是幂等的，审计里也只记这次真正动了谁。

    资格是布尔字段而不是一张关联表——判定那边（``reviews.permissions``）
    读的就是这些字段，这里只是它们唯一的写入口。
    """
    if flag not in QUALIFICATION_FLAGS:
        raise ValueError(f"{flag} 不是可以批量授予的资格字段。")

    targets = [user for user in users if getattr(user, flag) != value]
    if not targets:
        return 0

    with transaction.atomic():
        for user in targets:
            setattr(user, flag, value)
        User.objects.bulk_update(targets, [flag])

    record_audit(
        action=(
            "accounts.qualification.grant" if value else "accounts.qualification.revoke"
        ),
        user=actor,
        detail={
            "flag": flag,
            "user_ids": [user.pk for user in targets],
            "usernames": [user.get_username() for user in targets],
        },
        request=request,
    )
    return len(targets)


def set_avatar(*, profile, uploaded_file, actor, request=None):
    """换头像：新图先落盘，再把旧图从磁盘上删掉。

    ``profile`` 要是**数据库里那一份**（视图取出来的实例即可）：本函数先读
    ``profile.avatar`` 记下旧文件，才把新文件盖上去——实例若已被表单改过，
    这里读到的就是新图，删旧文件会变成删新文件。
    """
    previous_name = profile.avatar.name if profile.avatar else ""
    previous_storage = profile.avatar.storage if profile.avatar else None

    with transaction.atomic():
        profile.avatar = uploaded_file
        profile.save(update_fields=["avatar", "updated_at"])
        record_audit(
            action="accounts.avatar.update",
            user=actor,
            target=profile,
            detail={"replaced": bool(previous_name)},
            request=request,
        )

    # 文件系统不在事务里，所以删除放在提交之后：万一前面出错，顶多多留一个旧文件，
    # 不会出现「库里还指着这张图、磁盘上已经没了」。
    if previous_name:
        previous_storage.delete(previous_name)
    return profile


def clear_avatar(*, profile, actor, request=None):
    """删头像：清空字段并删掉文件；本来就没有头像时什么也不做。"""
    if not profile.avatar:
        return False
    name, storage = profile.avatar.name, profile.avatar.storage

    with transaction.atomic():
        profile.avatar = ""
        profile.save(update_fields=["avatar", "updated_at"])
        record_audit(
            action="accounts.avatar.clear",
            user=actor,
            target=profile,
            detail={},
            request=request,
        )

    storage.delete(name)
    return True
