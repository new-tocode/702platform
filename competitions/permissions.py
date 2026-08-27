"""Permission helpers for project-group competition registration."""

from projects.models import ProjectGroup


def is_competition_manager(user):
    """Return whether a user is an administrator or leads at least one group."""
    return bool(
        user
        and user.is_authenticated
        and (
            user.is_staff
            or ProjectGroup.objects.filter(leader_id=user.pk).exists()
        )
    )


def can_register_group(user, group):
    """Administrators may register any group; leaders may register their group."""
    return bool(
        user
        and user.is_authenticated
        and group
        and (user.is_staff or group.leader_id == user.pk)
    )
