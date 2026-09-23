"""Request tracing and first-login password enforcement middleware."""

import logging
import time
import uuid
from urllib.parse import urlencode

from django.shortcuts import redirect
from django.urls import reverse


logger = logging.getLogger(__name__)


class RequestLoggingMiddleware:
    """Log every request start/end and unexpected exception with context."""

    def __init__(self, get_response):
        self.get_response = get_response
        logger.debug(
            "middleware.initialized name=%s next=%s",
            self.__class__.__name__,
            getattr(get_response, "__qualname__", repr(get_response)),
        )

    def __call__(self, request):
        request.request_id = uuid.uuid4().hex[:12]
        request_started = time.perf_counter()
        request._request_started_at = request_started
        user_label = self._user_label(request)
        logger.info(
            "request.start method=%s path=%s query=%s user=%s remote=%s",
            request.method,
            request.path,
            request.META.get("QUERY_STRING", ""),
            user_label,
            request.META.get("REMOTE_ADDR", "-"),
            extra={"request_id": request.request_id},
        )

        try:
            response = self.get_response(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - request_started) * 1000
            logger.exception(
                "request.exception method=%s path=%s user=%s elapsed_ms=%.2f",
                request.method,
                request.path,
                user_label,
                elapsed_ms,
                extra={"request_id": request.request_id},
            )
            raise

        elapsed_ms = (time.perf_counter() - request_started) * 1000
        response["X-Request-ID"] = request.request_id
        logger.info(
            "request.end method=%s path=%s status=%s user=%s elapsed_ms=%.2f",
            request.method,
            request.path,
            response.status_code,
            self._user_label(request),
            elapsed_ms,
            extra={"request_id": request.request_id},
        )
        return response

    @staticmethod
    def _user_label(request):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return "anonymous"
        return f"{user.get_username()}(id={user.pk})"


class ForcePasswordChangeMiddleware:
    """Restrict users with an initial password to the password-change flow."""

    def __init__(self, get_response):
        self.get_response = get_response
        logger.debug("middleware.initialized name=%s", self.__class__.__name__)

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated or not user.must_change_password:
            return None

        allowed_paths = {
            reverse("accounts:password_change"),
            reverse("accounts:logout"),
        }
        if request.path in allowed_paths:
            logger.debug(
                "password_change.allow path=%s user=%s",
                request.path,
                user.get_username(),
                extra={"request_id": getattr(request, "request_id", "-")},
            )
            return None

        logger.warning(
            "password_change.redirect path=%s user=%s reason=must_change_password",
            request.path,
            user.get_username(),
            extra={"request_id": getattr(request, "request_id", "-")},
        )
        query = urlencode({"next": request.get_full_path()})
        return redirect(f"{reverse('accounts:password_change')}?{query}")
