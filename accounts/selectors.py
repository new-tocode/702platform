"""个人信息页要的只读派生：这个账号身上有哪些身份。

身份目录在 :mod:`core.roles`（有哪些身份、各自叫什么），判定在各应用的
``permissions``（谁有什么身份），这里只把两者对上，产出页面能直接渲染的形状。
顺序与后台「身份管理」分组的排法同源：全局身份按目录的 ``sort_order``（管理员 →
评审人 → 初审人 → 超级评审），对象身份随其后。

只读不写，所以不叫 services；跨应用取数走 ``projects.selectors``，不直接查
``ProjectGroup``。
"""

from dataclasses import dataclass

from django.utils.translation import gettext_lazy as _

from core.permissions import is_admin


@dataclass(frozen=True)
class Identity:
    """一条身份：叫什么，以及它落在哪些项目组上。

    全局身份没有依附的对象，``groups`` 因此是空的——模板据此决定只画一个标签，
    还是把组名一并列出来。
    """

    label: str
    groups: tuple = ()


def member_identities(user):
    """该用户持有的身份，按身份目录的顺序；没持有的不出现。

    对象身份（项目组联系人、项目组成员）只在真有组时才算一条，所以清单里不会
    出现「项目组成员：无」这种空条目。
    """
    if not (user and user.is_authenticated):
        return ()
    # 局部导入：accounts 不在加载期依赖 projects／reviews，依赖方向保持单向。
    from projects.selectors import groups_led_by, groups_of_member
    from reviews.permissions import (
        is_preliminary_reviewer,
        is_reviewer,
        is_super_reviewer,
    )

    identities = []
    if is_admin(user):
        identities.append(Identity(_("管理员")))
    if is_reviewer(user):
        identities.append(Identity(_("评审人")))
    if is_preliminary_reviewer(user):
        identities.append(Identity(_("初审人")))
    if is_super_reviewer(user):
        identities.append(Identity(_("超级评审")))

    led = tuple(group.name for group in groups_led_by(user))
    if led:
        identities.append(Identity(_("项目组联系人"), led))
    joined = tuple(group.name for group in groups_of_member(user))
    if joined:
        identities.append(Identity(_("项目组成员"), joined))
    return tuple(identities)
