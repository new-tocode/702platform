"""Authentication and profile lifecycle signals with audit-friendly logs."""

import logging

from django.contrib import messages
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profile, User


logger = logging.getLogger(__name__)


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, raw, **kwargs):
    if raw:
        logger.debug(
            "profile.skip user=%s reason=raw_fixture_load",
            instance.get_username(),
        )
        return
    if created:
        profile, profile_created = Profile.objects.get_or_create(user=instance)
        logger.info(
            "profile.created user=%s user_id=%s profile_id=%s created=%s",
            instance.get_username(),
            instance.pk,
            profile.pk,
            profile_created,
        )


@receiver(user_logged_in)
def log_user_login(sender, request, user, **kwargs):
    logger.info(
        "auth.login.success username=%s user_id=%s must_change_password=%s path=%s",
        user.get_username(),
        user.pk,
        user.must_change_password,
        getattr(request, "path", "-"),
        extra={"request_id": getattr(request, "request_id", "-")},
    )


@receiver(user_logged_in)
def remind_reviewer_of_pending_reviews(sender, request, user, **kwargs):
    """Nudge a reviewer about unfinished reviews as soon as they log in.

    The reminder is a flash message rather than a redirect: logging in should
    not silently change the page the user asked for, and the same count is shown
    persistently on the member centre. 初审 and 评审 are counted and named
    separately — they are different tasks, and one number says nothing about the
    other.
    """
    if request is None:
        return
    # Local imports keep accounts free of load-time dependencies on other apps.
    from projects.permissions import is_project_reviewer
    from reviews.services import (
        count_pending_preliminary_reviews,
        count_pending_reviews,
    )

    if not is_project_reviewer(user):
        return
    pending_preliminary = count_pending_preliminary_reviews(user)
    pending = count_pending_reviews(user)
    parts = []
    if pending_preliminary:
        parts.append(f"{pending_preliminary} 份项目书待初审")
    if pending:
        parts.append(f"{pending} 份项目书待评审")
    if not parts:
        return
    # fail_silently: a login must never break because the reminder could not be
    # queued — e.g. a programmatic login outside the middleware chain, where the
    # request carries no message storage.
    messages.warning(
        request,
        f"你有 {'、'.join(parts)}，请前往「评审」处理。",
        fail_silently=True,
    )
    logger.info(
        "reviews.reminder.login user=%s pending_preliminary=%s pending=%s",
        user.get_username(),
        pending_preliminary,
        pending,
        extra={"request_id": getattr(request, "request_id", "-")},
    )


@receiver(user_login_failed)
def log_user_login_failed(sender, credentials, request, **kwargs):
    # Never log the supplied password or any credential value besides username.
    logger.warning(
        "auth.login.failure username=%s path=%s remote=%s",
        credentials.get("username", "-"),
        getattr(request, "path", "-") if request else "-",
        request.META.get("REMOTE_ADDR", "-") if request else "-",
        extra={"request_id": getattr(request, "request_id", "-") if request else "-"},
    )
