"""Permission helpers for project groups and their computed contact identity.

Contact identity (``ProjectGroup.leader``) is never materialised into a stored
membership or auth group; every helper here derives it from the leader field so
there is a single source of truth. Other apps import these helpers instead of
querying ``ProjectGroup`` directly, which keeps the judgment in one place.

评审资格与「凭评审身份能不能看这个组」**不在这里**——那是评审应用的口径，住在
``reviews/permissions.py``；本模块只在 ``can_view_group`` 里委托一次。
"""

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
        and (user.is_staff or group.leader_id == user.pk)
    )


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
    if user.is_staff or group.members.filter(pk=user.pk).exists():
        return True
    # Local import keeps the projects app free of a hard dependency on reviews.
    from reviews.permissions import has_review_claim

    return has_review_claim(user, group)


def can_use_equipment(user):
    """Borrowing is limited to project-group members (and administrators)."""
    return bool(
        user
        and user.is_authenticated
        and (user.is_staff or is_project_member(user))
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
    if user.is_staff:
        return list(ProjectGroup.objects.values_list("pk", flat=True))
    return contact_group_ids(user)


def groups_visible_to(user):
    """Return the project groups the user may see on the member project page.

    Staff and contacts see every group. A member who already belongs to a group
    sees only their own. A logged-in user with no group sees every group so they
    can apply to join one.
    """
    if not (user and user.is_authenticated):
        return ProjectGroup.objects.none()
    if user.is_staff or is_project_contact(user):
        return ProjectGroup.objects.all()
    own = ProjectGroup.objects.filter(members=user)
    if own.exists():
        return own
    return ProjectGroup.objects.all()
