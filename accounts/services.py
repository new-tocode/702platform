"""账号相关的写操作。

目前只有一件事：授予／撤销评审资格。它是后台批量动作的落点，要事务、要审计，
所以不写在 admin 里——那里过去改资格连审计都不留。
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
