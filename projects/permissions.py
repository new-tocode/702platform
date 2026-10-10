"""Permission helpers for project groups and their computed contact identity.

Contact identity (``ProjectGroup.leader``) is never materialised into a stored
membership or auth group; every helper here derives it from the leader field so
there is a single source of truth. Other apps import these helpers instead of
querying ``ProjectGroup`` directly, which keeps the judgment in one place.

评审资格与「凭评审身份能不能看这个组」**不在这里**——那是评审应用的口径，住在
``reviews/permissions.py``；本模块只在 ``can_view_group`` 里委托一次。
"""

from core.permissions import is_admin

from .models import ProjectGroup


def is_project_contact(user):
    """Return whether the user is the contact (leader) of any project group."""
    return bool(
        user
        and user.is_authenticated
        and ProjectGroup.objects.filter(leader_id=user.pk).exists()
    )


def is_project_member(user):
    """Return whether the user belongs to at least one project group.

    A group's contact is always kept in its member list, so contacts are members
    too.
    """
    return bool(
        user
        and user.is_authenticated
        and ProjectGroup.objects.filter(members=user).exists()
    )


def can_manage_group(user, group):
    """Administrators manage any group; a contact manages only their own."""
    return bool(
        user
        and user.is_authenticated
        and group
        and (is_admin(user) or group.leader_id == user.pk)
    )


def can_decide_group_create_requests(user):
    """创建项目组申请的审核人：全体管理员。

    申请送到管理员的「评审」页（评审侧据此决定给不给看那份待办），任一位管理员
    同意即通过，其余人无需再审。判定只此一处，视图门槛与页面装配都走它。

    「谁算管理员」委托 :func:`core.permissions.is_admin`；这里保留业务语义名，
    让调用方问的是「谁能审建组申请」，而不是「他是不是 staff」。
    """
    return is_admin(user)


def can_view_group(user, group):
    """Group detail is visible to staff, its members, and whoever reviews it.

    This side answers the project-group question only (staff, members); the
    review half — a super reviewer looking at an in-progress round, or anyone
    holding a task on this group — is the review app's call and is delegated
    below. The grants are unioned, not returned early: an account that is both a
    super reviewer and an ordinary reviewer must not lose the access its own
    review task gives it the moment the round is decided.
    """
    if not (user and user.is_authenticated and group):
        return False
    if is_admin(user) or group.members.filter(pk=user.pk).exists():
        return True
    # Local import keeps the projects app free of a hard dependency on reviews.
    from reviews.permissions import has_review_claim

    return has_review_claim(user, group)


def can_use_equipment(user):
    """Borrowing is limited to project-group members (and administrators)."""
    return bool(
        user
        and user.is_authenticated
        and (is_admin(user) or is_project_member(user))
    )


def contact_group_ids(user):
    """Primary keys of the groups the user is the contact of."""
    if not (user and user.is_authenticated):
        return []
    return list(
        ProjectGroup.objects.filter(leader_id=user.pk).values_list("pk", flat=True)
    )


def member_group_ids(user):
    """Primary keys of the groups the user belongs to."""
    if not (user and user.is_authenticated):
        return []
    return list(
        ProjectGroup.objects.filter(members=user).values_list("pk", flat=True)
    )


def manageable_group_ids(user):
    """Primary keys of the groups the user may manage (all for staff)."""
    if not (user and user.is_authenticated):
        return []
    if is_admin(user):
        return list(ProjectGroup.objects.values_list("pk", flat=True))
    return contact_group_ids(user)


def groups_visible_to(user):
    """Return the project groups the user may see on the member project page.

    **登录即可见全部**，不再按「有没有组」分档——这一页是「社团里有哪些组、
    我想进哪一个」的入口，看不出别的组就没有比较可言。想只看自己参与的组，
    用页面上的「我的项目组」筛选（`?mine=1`，那是筛选，不是可见范围）。
    未登录 → 空查询集。

    注意这里**只管列表**：详情页与项目书取件是另一道门（:func:`can_view_group`，
    它还并进评审侧的主张），两者不是同一个口径。
    """
    if not (user and user.is_authenticated):
        return ProjectGroup.objects.none()
    return ProjectGroup.objects.all()
