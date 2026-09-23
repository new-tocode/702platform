"""项目组的只读查询：按人取组。

判定「谁算联系人、谁算成员」仍归 :mod:`projects.permissions`（那边的
``contact_group_ids``／``member_group_ids`` 只给主键）；页面上要连组名一起显示，
拿主键再回头查一次组就成了两趟。这里把「按人取组」整句收下来，只读不写。

依赖方向不变：跨应用问项目组时走这里或 ``permissions``，不直接查
``ProjectGroup`` 的模型。
"""

from .models import ProjectGroup


def groups_led_by(user):
    """该用户作为联系人的项目组（查询集）。"""
    if not (user and user.is_authenticated):
        return ProjectGroup.objects.none()
    return ProjectGroup.objects.filter(leader_id=user.pk)


def groups_of_member(user):
    """该用户所属的项目组（查询集）。

    联系人一定在成员名单里（``ProjectGroup.save`` 保证），所以自己带的组也会
    出现在这里——与后台「项目组成员」名册的口径一致。
    """
    if not (user and user.is_authenticated):
        return ProjectGroup.objects.none()
    return ProjectGroup.objects.filter(members=user)
