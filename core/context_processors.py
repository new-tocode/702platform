from .registry import get_entries_for_user


def operation_entries(request):
    """Make registered member operations available to every base template."""
    return {"operation_entries": get_entries_for_user(getattr(request, "user", None))}
