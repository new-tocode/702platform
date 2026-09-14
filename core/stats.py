"""平台概览数字。

社团规模下四条 COUNT 足够便宜，不做缓存；跨应用引用因此放在函数内部导入，
避免应用加载期互相牵连。

这些数字不对外公开：在册人数、项目组数、竞赛与设备规模都属于内部信息，
只呈现给管理员与项目组联系人，展示位置在成员中心而非公开首页。
"""

from django.contrib.auth import get_user_model
from django.utils import timezone


def can_view_platform_overview(user):
    """概览数字的可见范围：管理员与项目组联系人。

    判定依据仍是 ``projects.permissions`` 的唯一真相源；这里只把「谁算联系人」
    转成一个展示层可用的布尔判断。
    """
    if not (user and user.is_authenticated):
        return False
    if user.is_staff or user.is_superuser:
        return True
    # 局部导入：让 core 不在模块加载期就依赖 projects。
    from projects.permissions import is_project_contact

    return is_project_contact(user)


def platform_overview():
    """返回成员中心展示用的四个计数。"""
    from competitions.models import Competition
    from equipment.models import EquipmentBorrow
    from projects.models import ProjectGroup

    return {
        "member_count": get_user_model().objects.filter(is_active=True).count(),
        "group_count": ProjectGroup.objects.count(),
        "open_competition_count": Competition.objects.filter(
            is_open=True,
            deadline__gte=timezone.now(),
        ).count(),
        "borrowed_count": EquipmentBorrow.objects.filter(
            status=EquipmentBorrow.BORROWED,
        ).count(),
    }
