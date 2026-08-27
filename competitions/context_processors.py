"""Template context for permission-aware member navigation."""

from projects.models import ProjectGroup


def competition_navigation(request):
    """Expose the competition entry only to usable competition managers."""
    user = getattr(request, "user", None)
    can_manage_competitions = bool(
        user
        and user.is_authenticated
        and not user.must_change_password
        and (
            user.is_staff
            or ProjectGroup.objects.filter(leader_id=user.pk).exists()
        )
    )
    return {"can_manage_competitions": can_manage_competitions}
