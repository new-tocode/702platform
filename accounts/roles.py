"""成员身份的展示口径。

平台有五类使用者：未登录游客、未加入项目组的成员、项目组成员、项目组联系人、
管理员。这里把「已登录的这个人是谁」收敛成一个标签供界面显示；判定依据仍是
``projects.permissions`` 里的唯一真相源，本模块不自己查 ProjectGroup。
"""

ADMIN = "管理员"
CONTACT = "项目组联系人"
GROUP_MEMBER = "项目组成员"
NO_GROUP = "未加入项目组"
GUEST = "游客"


def describe_member(user):
    """按权限从高到低返回身份标签。

    管理员同时可能是联系人，这里只显示最高权限的那一个；
    评审资格是独立的用户属性，由调用方单独展示，不参与这里的排序。
    """
    if not (user and user.is_authenticated):
        return GUEST
    if user.is_staff or user.is_superuser:
        return ADMIN
    # 局部导入：让 accounts 不在模块加载期就依赖 projects。
    from projects.permissions import contact_group_ids, member_group_ids

    if contact_group_ids(user):
        return CONTACT
    if member_group_ids(user):
        return GROUP_MEMBER
    return NO_GROUP
