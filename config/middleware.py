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
        # 与审计日志同一个口径（core.audit.get_client_ip）：反代下 REMOTE_ADDR
        # 恒为 127.0.0.1，直接用它会让每一行访问日志的来源都失去意义。
        from core.audit import get_client_ip

        logger.info(
            "request.start method=%s path=%s query=%s user=%s remote=%s",
            request.method,
            request.path,
            request.META.get("QUERY_STRING", ""),
            user_label,
            get_client_ip(request) or "-",
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


class SecurityHeadersMiddleware:
    """补上 Django 自己不发的那两个安全响应头。

    ``SecurityMiddleware`` 已经负责 nosniff、Referrer-Policy 与 X-Frame-Options，
    这里只管它不管的两条：

    * **CSP**——只以 ``Report-Only`` 发出：浏览器**不会**拦任何东西，只在控制台
      报出「这条策略会拦下什么」。用它是为了在真正启用前把该修的先修掉，因为
      CSP 拦错的表现是页面静默失效（按钮没反应、样式没加载），比报错难查得多。

      策略按**目标状态**写（``script-src 'self'``，不含 ``'unsafe-inline'``），
      所以现在只会有两类报告，都是真的该处理的：

      1. ``templates/competitions/register.html`` 里那处内联 ``<script>``——
         把它挪进 ``static/js/`` 之后本站就没有内联脚本了（全站无内联事件
         处理器、无内联样式）；
      2. ``/admin/`` 后台自带内联脚本与样式——将来切强制时给后台单独放宽，
         或让后台维持报告模式。

      报出的其它条目才是意外，值得逐条看。
    * **Permissions-Policy**——关掉本站用不到的浏览器特性。作用是缩小被第三方
      脚本（或浏览器内中间人）滥用的面：这个站不需要摄像头、麦克风、定位与支付。
    """

    CSP = "; ".join(
        [
            "default-src 'self'",
            "base-uri 'self'",
            "form-action 'self'",
            "frame-ancestors 'none'",
            "object-src 'none'",
            "img-src 'self' data:",
            "style-src 'self'",
            "script-src 'self'",
            "connect-src 'self'",
            "font-src 'self'",
        ]
    )
    PERMISSIONS_POLICY = "geolocation=(), camera=(), microphone=(), payment=(), usb=()"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        # setdefault：视图或下游中间件若已经自己发过，就不要覆盖它。
        response.setdefault("Content-Security-Policy-Report-Only", self.CSP)
        response.setdefault("Permissions-Policy", self.PERMISSIONS_POLICY)
        return response


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
