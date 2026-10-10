"""项目组的只读查询：按人取组、按关键字搜组。

判定「谁算联系人、谁算成员」仍归 :mod:`projects.permissions`（那边的
``contact_group_ids``／``member_group_ids`` 只给主键）；页面上要连组名一起显示，
拿主键再回头查一次组就成了两趟。这里把「按人取组」整句收下来，只读不写。

依赖方向不变：跨应用问项目组时走这里或 ``permissions``，不直接查
``ProjectGroup`` 的模型。
"""

from django.db.models import Count, IntegerField, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce

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


def search_groups(groups, *, query=""):
    """在给定查询集里按一个关键字过滤项目组，空关键字原样返回。

    关键字同时扫组名与三个位置上的姓名——联系人、组员、指导老师：找组的人心里
    想的是「张三那个组」，不该先判断这句话是组名还是人名。姓名既匹配
    ``Profile.full_name``（页面上显示的就是它），也匹配 ``username``：后者是
    ``full_name`` 为空时页面回退显示的名字，页面上看得见就该搜得着。

    过滤跨 ``members`` / ``advisors`` 两个一对多关系，同一组会被 JOIN 出多行，
    结尾用 ``distinct`` 收回一行。

    **别在这条 join 上直接数人**：``Count("members")`` 落在同一条被过滤过的
    join 上时，数出来的只是「命中的那几个人」——搜一名成员、卡片写「成员 1 人」，
    而同屏的名单列着 5 个。要数真实人数用 :func:`annotate_member_count`。

    可见范围由调用方先行收窄（``permissions.groups_visible_to``）；这里只管
    关键字，不管权限。
    """
    keyword = (query or "").strip()
    if not keyword:
        return groups
    return groups.filter(
        Q(name__icontains=keyword)
        | Q(leader__username__icontains=keyword)
        | Q(leader__profile__full_name__icontains=keyword)
        | Q(members__username__icontains=keyword)
        | Q(members__profile__full_name__icontains=keyword)
        | Q(advisors__name__icontains=keyword)
    ).distinct()


def annotate_member_count(groups):
    """给项目组查询集加 ``member_count``：**该组的真实成员数**。

    数的是这个组**有几个人**，与查询集上任何过滤（搜索、「我的项目组」）无关——
    卡片上的数字因此恒等于同屏名单的长度。做法是子查询：计数自己走一条
    ``projects_projectgroup_members`` 的 join，不与被过滤的那条共用。

    为什么不用 ``Count("members")``：见 :func:`search_groups` 的说明——那个数字
    会跟着搜索一起变小。``Coalesce`` 只是兜底（``ProjectGroup.save`` 保证联系人
    恒为成员，正常数据下数不出 0），省得模板里的 ``blocktranslate count`` 拿到
    ``None``。
    """
    member_counts = (
        ProjectGroup.members.through.objects.filter(projectgroup=OuterRef("pk"))
        .values("projectgroup")
        .annotate(total=Count("user"))
        .values("total")
    )
    return groups.annotate(
        member_count=Coalesce(
            Subquery(member_counts, output_field=IntegerField()),
            0,
        )
    )
