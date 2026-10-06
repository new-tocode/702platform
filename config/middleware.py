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

    * **CSP（强制）**——先前只以 ``Report-Only`` 发出，用来在真拦之前摸清「会拦下
      什么」。现在切到强制。切之前该修的都修了：全站唯一一处内联 ``<script>``
      （竞赛报名页的成员过滤）已挪进 ``static/js/registration.js``，元素 id 改由
      data 属性传递；全站没有内联事件处理器、没有内联 ``style=``、没有外部资源。

      唯一被放宽的是 ``/admin/``：Django admin 的模板自带内联脚本与内联样式，
      那是框架自己的模板，收不掉。后台是「只有 staff 能进、代码全是我们自己的」
      的面，所以单独给它 ``'unsafe-inline'``——比让后台静默失效强，也比为了它把
      整站放宽要好。

      **强制 CSP 拦错的表现是页面静默失效**（按钮没反应、样式没加载、下拉框不过滤），
      比报错难查得多。所以今后每收紧一条指令，都要先在真实浏览器里把相关页面点一遍，
      而不是靠读代码判断「应该没问题」。
    * **Permissions-Policy**——关掉本站用不到的浏览器特性。作用是缩小被第三方
      脚本（或浏览器内中间人）滥用的面：这个站不需要摄像头、麦克风、定位与支付。
    """

    #: 前台策略。全站资源都自托管（没有 CDN、没有外链字体），所以每条都收到 'self'。
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

    #: 后台策略：与前台只差两处 ``'unsafe-inline'``。Django admin 的模板里有内联
    #: 脚本（如 change form 的 prepopulate、actions 的确认框）与内联样式，用前台的
    #: 策略会把后台拦成半残——而那种坏法是静默的。
    ADMIN_CSP = "; ".join(
        [
            "default-src 'self'",
            "base-uri 'self'",
            "form-action 'self'",
            "frame-ancestors 'none'",
            "object-src 'none'",
            "img-src 'self' data:",
            "style-src 'self' 'unsafe-inline'",
            "script-src 'self' 'unsafe-inline'",
            "connect-src 'self'",
            "font-src 'self'",
        ]
    )

    ADMIN_PREFIX = "/admin/"

    PERMISSIONS_POLICY = "geolocation=(), camera=(), microphone=(), payment=(), usb=()"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        policy = (
            self.ADMIN_CSP
            if request.path.startswith(self.ADMIN_PREFIX)
            else self.CSP
        )
        # setdefault：视图或下游中间件若已经自己发过，就不要覆盖它。
        response.setdefault("Content-Security-Policy", policy)
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
