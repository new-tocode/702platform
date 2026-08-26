"""Authentication and profile lifecycle signals with audit-friendly logs."""

import logging

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
