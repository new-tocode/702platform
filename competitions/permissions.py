"""Permission helpers for project-group competition registration.

The contact judgment itself lives in ``projects.permissions``; these helpers add
the competition-specific verb on top of it so call sites do not query
``ProjectGroup`` directly.
"""

from projects.permissions import can_manage_group, is_project_contact


def is_competition_manager(user):
    """Return whether a user is an administrator or a project-group contact."""
    return bool(
        user
        and user.is_authenticated
        and (user.is_staff or is_project_contact(user))
    )


def can_register_group(user, group):
    """Administrators may register any group; contacts only their own."""
    return can_manage_group(user, group)
