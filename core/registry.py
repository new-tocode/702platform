"""A small registry for permission-aware member operation entries."""

from dataclasses import dataclass
import logging
from threading import RLock
from typing import Callable

from django.urls import NoReverseMatch, reverse


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OperationEntry:
    key: str
    label: str
    description: str
    url_name: str
    required_permission: str | None = None
    visible_when: Callable | None = None
    staff_only: bool = False
    sort_order: int = 100

    @property
    def url(self):
        return reverse(self.url_name)


_ENTRIES = {}
_LOCK = RLock()


def register_entry(
    *,
    key,
    label,
    description,
    url_name,
    required_permission=None,
    visible_when=None,
    staff_only=False,
    sort_order=100,
):
    """Register or replace one operation entry by stable key.

    AppConfig.ready() can safely call this more than once during Django's
    development autoreload because registration is idempotent by key.
    """
    entry = OperationEntry(
        key=key,
        label=label,
        description=description,
        url_name=url_name,
        required_permission=required_permission,
        visible_when=visible_when,
        staff_only=staff_only,
        sort_order=sort_order,
    )
    with _LOCK:
        previous = _ENTRIES.get(key)
        _ENTRIES[key] = entry
    logger.debug(
        "operation_registry.register key=%s url_name=%s replaced=%s",
        key,
        url_name,
        previous is not None,
    )
    return entry


def unregister_entry(key):
    """Remove one registered entry, primarily for isolated tests."""
    with _LOCK:
        removed = _ENTRIES.pop(key, None)
    logger.debug(
        "operation_registry.unregister key=%s removed=%s",
        key,
        removed is not None,
    )


def get_registered_entries():
    with _LOCK:
        return tuple(sorted(_ENTRIES.values(), key=lambda entry: (entry.sort_order, entry.key)))


def _entry_visible_to_user(entry, user):
    if not user or not user.is_authenticated or getattr(user, "must_change_password", False):
        return False
    if entry.staff_only and not user.is_staff:
        return False
    if entry.required_permission and not user.has_perm(entry.required_permission):
        return False
    if entry.visible_when:
        try:
            return bool(entry.visible_when(user))
        except Exception:
            logger.exception(
                "operation_registry.visibility_error key=%s user=%s",
                entry.key,
                user.get_username(),
            )
            return False
    return True


def get_entries_for_user(user):
    """Return only resolvable entries visible to the current authenticated user."""
    visible = []
    for entry in get_registered_entries():
        if not _entry_visible_to_user(entry, user):
            continue
        try:
            entry.url
        except NoReverseMatch:
            logger.exception(
                "operation_registry.invalid_url key=%s url_name=%s",
                entry.key,
                entry.url_name,
            )
            continue
        visible.append(entry)
    logger.debug(
        "operation_registry.resolve user=%s visible_keys=%s",
        user.get_username() if user and user.is_authenticated else "anonymous",
        [entry.key for entry in visible],
    )
    return tuple(visible)
