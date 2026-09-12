"""Template context for permission-aware member navigation."""

from .permissions import is_competition_manager


def competition_navigation(request):
    """Expose competition management capability to member templates."""
    user = getattr(request, "user", None)
    can_manage_competitions = bool(
        user
        and user.is_authenticated
        and not getattr(user, "must_change_password", False)
        and is_competition_manager(user)
    )
    return {"can_manage_competitions": can_manage_competitions}
