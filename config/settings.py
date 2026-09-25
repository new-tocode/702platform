"""Django settings for the competition club platform.

The settings are intentionally explicit: local development should be easy to
inspect, while production values can be supplied through environment variables.
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    """Read a boolean environment variable with predictable semantics."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-development-only-change-me",
)
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",")
    if host.strip()
]


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "accounts.apps.AccountsConfig",
    "notices.apps.NoticesConfig",
    "media.apps.MediaConfig",
    "content.apps.ContentConfig",
    "projects.apps.ProjectsConfig",
    "competitions.apps.CompetitionsConfig",
    "reviews.apps.ReviewsConfig",
    "equipment.apps.EquipmentConfig",
    "discussion.apps.DiscussionConfig",
    "core.apps.CoreConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    # 中英双语：按地址上的 /en/ 前缀激活对应语言（i18n_patterns 必需）。
    # 必须排在 SessionMiddleware 之后、CommonMiddleware 之前（Django 的要求）。
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "config.middleware.RequestLoggingMiddleware",
    "config.middleware.ForcePasswordChangeMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "competitions.context_processors.competition_navigation",
                "core.context_processors.operation_entries",
                "core.context_processors.nav_section",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DJANGO_DB_NAME", "club702_dev"),
        "USER": os.environ.get("DJANGO_DB_USER", ""),
        "PASSWORD": os.environ.get("DJANGO_DB_PASSWORD", ""),
        "HOST": os.environ.get("DJANGO_DB_HOST", "127.0.0.1"),
        "PORT": os.environ.get("DJANGO_DB_PORT", "5432"),
    }
}


AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "accounts:member_home"
LOGOUT_REDIRECT_URL = "accounts:home"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


LANGUAGE_CODE = "zh-hans"
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "Asia/Shanghai")
USE_I18N = True
USE_TZ = True

# 界面中英双语。中文是**源语言**：模板与代码里写的 msgid 本身就是中文，所以中文
# 不需要翻译文件（取不到译文时 gettext 原样返回 msgid）；英文译文在
# locale/en/LC_MESSAGES/django.po。后台 /admin/ 不在双语范围内，见 config/urls.py。
LANGUAGES = [
    ("zh-hans", "中文"),
    ("en", "English"),
]
LOCALE_PATHS = [BASE_DIR / "locale"]


STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "mediafiles"

# 静态资源指纹：生产环境 collectstatic 后，{% static %} 解析为 app.<hash>.css，
# 与 Nginx 的 expires 7d 配合，部署即让浏览器里的旧样式失效。开发环境不加指纹，
# 否则每次改 CSS 都得重新 collectstatic；本地看到旧样式时硬刷新即可。
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"
        )
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Cookie 与安全头。
#
# 两个 Secure 标志**默认开启**：线上是全程 https（服务器自己 443，或上层代理
# 终结 TLS），IP 直连也一样，所以给会话与 CSRF Cookie 加上 Secure 不挡任何人。
# 以前默认关着，等于把「登录后会话可被同网段明文取走」交给部署者去发现——这类
# 默认值该站在安全那一侧。
#
# 唯一的例外是纯 http 的部署，那种环境要在 env.sh 里显式改回 0，否则浏览器不会
# 带上会话 Cookie，谁都登录不了。
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = env_bool("DJANGO_SESSION_COOKIE_SECURE", True)
CSRF_COOKIE_SECURE = env_bool("DJANGO_CSRF_COOKIE_SECURE", True)
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# 整站跳 https。**默认关**：现用的证书借自另一个已备案的站点，随时可能收回；
# 而确实有人用 http://IP 直接访问，硬跳会把 IP 这条入口打到域名上去（那个域名
# 还不属于本平台）。拿到自己的证书后再打开。
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", False)

# HSTS。**默认关，且要格外谨慎**：一旦生效，浏览器会在有效期内拒绝一切非 https
# 访问，用户点「继续访问」也绕不过去。证书是借来的情况下开它，等证书被收回时
# 站点就被锁死了——只能换域名，或者让每个用户去清 HSTS 缓存。拿到本平台自己的、
# 稳定的证书后再考虑，初值也建议先给 60 秒试水。
SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_SECURE_HSTS_SECONDS", "0"))
if SECURE_HSTS_SECONDS:
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool(
        "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", False
    )
    SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", False)

# 上面两处「有意关闭」对应的告警一并静音。不静音的话，check --deploy 的输出里
# 永远压着这两条，deploy.sh 的上线门禁就没法用「有任何告警即失败」这条简单规则
# ——一条永远为真的告警会把整道门禁变成摆设。
#
# 静音条件与关闭条件绑在一起：拿到自己的证书、把两个开关打开之后，告警自动回来。
SILENCED_SYSTEM_CHECKS = [
    check
    for check, silenced in (
        ("security.W004", not SECURE_HSTS_SECONDS),
        ("security.W008", not SECURE_SSL_REDIRECT),
    )
    if silenced
]

# Reverse proxy / HTTPS support. Set DJANGO_PROXY_SSL_HEADER=1 when TLS is
# terminated by Nginx or an equivalent trusted proxy that always sets
# X-Forwarded-Proto itself.
if env_bool("DJANGO_PROXY_SSL_HEADER", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]


LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "detailed": {
            "format": (
                "[{asctime}] {levelname} {name} "
                "request_id={request_id} {message}"
            ),
            "style": "{",
            "()": "config.logging.RequestContextFormatter",
        },
        "standard": {
            "format": "[{asctime}] {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "detailed",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_DIR / "django.log"),
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "encoding": "utf-8",
            "formatter": "detailed",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console", "file"],
            "level": "ERROR",
            "propagate": False,
        },
        "django.server": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
        "accounts": {
            "handlers": ["console", "file"],
            "level": "DEBUG",
            "propagate": False,
        },
        "config": {
            "handlers": ["console", "file"],
            "level": "DEBUG",
            "propagate": False,
        },
        "projects": {
            "handlers": ["console", "file"],
            "level": "DEBUG",
            "propagate": False,
        },
        "competitions": {
            "handlers": ["console", "file"],
            "level": "DEBUG",
            "propagate": False,
        },
        "reviews": {
            "handlers": ["console", "file"],
            "level": "DEBUG",
            "propagate": False,
        },
        "equipment": {
            "handlers": ["console", "file"],
            "level": "DEBUG",
            "propagate": False,
        },
        "core": {
            "handlers": ["console", "file"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
}


# ---------------------------------------------------------------------------
# 生产配置自检
#
# 上面每一项都有安全默认值，唯独 SECRET_KEY 只能由部署者给对，而漏设的后果是
# 静默的：站点照常起来，只是会话签名用的是公开在源码里的那把钥匙，任何人都能
# 伪造出有效的会话 Cookie。manage.py check --deploy 会提示，但那要有人主动去跑。
#
# 所以这一条改成拒绝启动：起不来是响的，起得来但是错的才是危险的。
# 本地开发不受影响——本地本来就用这把开发密钥。
#
# DEBUG 不在这里判：它由 deploy/deploy.sh 上线时的 check --deploy 门禁拦下
# （security.W018），那份检查同时覆盖 HSTS、Cookie、SSL 跳转等其余项，比
# 散在 settings 里的逐条判断更不容易漏。
if not DEBUG and SECRET_KEY == "django-insecure-development-only-change-me":
    raise ImproperlyConfigured(
        "生产环境必须设置 DJANGO_SECRET_KEY（不能沿用源码里的开发默认值）。"
        "可用 `python -c \"from django.core.management.utils import "
        "get_random_secret_key; print(get_random_secret_key())\"` 生成。"
    )
