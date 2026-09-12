"""首页概览数字。

社团规模下四条 COUNT 足够便宜，不做缓存；跨应用引用因此放在函数内部导入，
避免应用加载期互相牵连。
"""

from django.contrib.auth import get_user_model
from django.utils import timezone


def platform_overview():
    """返回公开门户展示用的四个计数。"""
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
