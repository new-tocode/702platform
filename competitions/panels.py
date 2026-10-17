"""项目组详情页上的「竞赛报名」区块。

与 :mod:`reviews.panels` 同一个理由：装配留在拥有数据的应用里，调用方
（``projects.views.group_detail``）**在函数体内**局部 import 本模块——提到模块级就会
把 ``competitions → projects`` 这条加载期依赖反过来，成环（见
:file:`docs/更新维护/模块与关系.md` §2）。

这里不判可见性：能打开项目组详情页的人（本组成员、管理员、评审人）就看得到本组报了
哪些竞赛，门槛已由 ``projects.permissions.can_view_group`` 把住。
"""

from .models import CompetitionRegistration


def group_detail_context(*, group):
    """本组报名的竞赛，用模型默认排序（最近报名的在前）。

    报名记录没有状态字段——放弃即删除，所以取出来的就是「当前报名」的那几场；
    已截止的竞赛仍留在列表里，由模板按 ``is_registration_open`` 标出状态。
    """
    return {
        "competition_registrations": (
            CompetitionRegistration.objects.filter(group=group)
            .select_related("competition", "team_leader__profile")
            .prefetch_related("members__profile")
        )
    }
