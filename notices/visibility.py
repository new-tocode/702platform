"""Single place that decides which notices a member may see.

List and detail views both go through :func:`member_visible_notices`, so the
visibility rule cannot drift between the two. Contact-only notices are computed
from ``projects.permissions.is_project_contact`` rather than a stored group.
"""

from django.db.models import Q

from projects.permissions import is_project_contact

from .models import Notice


def public_visible_notices():
    """Public notices, visible to visitors and members alike."""
    return Notice.objects.filter(scope=Notice.PUBLIC)


def member_visible_notices(user):
    """Notices visible to a logged-in, password-completed member.

    Internal notices come from the member's auth groups; contact-only notices
    are included when the member is the contact of any project group.
    """
    query = Q(scope=Notice.INTERNAL, visible_groups__in=user.groups.all())
    if is_project_contact(user):
        query |= Q(scope=Notice.CONTACTS)
    return Notice.objects.filter(query).distinct()
