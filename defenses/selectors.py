"""线下模拟答辩的只读查询：两个列表与详情页要的评论。

判定仍归 :mod:`defenses.permissions`；这里只回答「按状态取哪些、按什么顺序」。
"""

from django.db.models import Count

from .models import DefenseRequest


def _scheduled(status):
    """某一状态的申请，新的在前，并带上评论条数。

    ``comment_count`` 数的是整条讨论（含编辑留痕），因为页面上的「N 条讨论」
    就是给人看这条申请下面发生过多少事。
    """
    return (
        DefenseRequest.objects.filter(status=status)
        .select_related("group", "applicant__profile", "closed_by__profile")
        .annotate(comment_count=Count("comments"))
        .order_by("-created_at", "-id")
    )


def open_requests():
    """「安排中」列表：还在讨论排期的申请。"""
    return _scheduled(DefenseRequest.OPEN)


def closed_requests():
    """「已确定」列表：已关闭、只读的申请。"""
    return _scheduled(DefenseRequest.CLOSED)


def requests_for_group(group):
    """某个项目组自己的申请，新的在前——项目组管理页的入口面板用。"""
    return (
        DefenseRequest.objects.filter(group=group)
        .select_related("applicant__profile")
        .order_by("-created_at", "-id")
    )


def request_detail_queryset():
    """详情页要的申请：连申请人、关闭人与评论作者一并取好。"""
    return DefenseRequest.objects.select_related(
        "group",
        "applicant__profile",
        "closed_by__profile",
    ).prefetch_related("comments__author__profile")
