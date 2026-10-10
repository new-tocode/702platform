"""settings 里的判定逻辑单测。

两条主线，都是「写坏了不会有报错、只会静默降级」的地方：

- **快速口令哈希只该在测试进程生效**：判定写坏（比如只认 ``sys.argv[1]``，碰上
  ``manage.py --settings=x test`` 就漏了）会让生产静默落到弱哈希上。
- **每个自家 app 都要有自己的 logger**：漏一个，那个 app 的 ``logger.info`` 连级别
  检查都过不去、``logger.warning`` 只经 ``lastResort`` 落到 stderr，都不进
  ``logs/django.log``——排查时会以为「什么都没发生」。
"""

import logging
import logging.handlers
from pathlib import Path
from uuid import uuid4

from django.apps import apps
from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .middleware import SecurityHeadersMiddleware
from .settings import running_tests


class RunningTestsDetectionTests(SimpleTestCase):
    def test_recognises_the_test_command(self):
        for argv in (
            ["manage.py", "test"],
            ["manage.py", "test", "accounts"],
            ["manage.py", "--settings=config.settings", "test", "--keepdb"],
            ["django-admin", "test", "--parallel"],
        ):
            with self.subTest(argv=argv):
                self.assertTrue(running_tests(argv))

    def test_other_commands_are_not_mistaken_for_tests(self):
        for argv in (
            ["manage.py", "runserver"],
            ["manage.py", "migrate"],
            ["manage.py", "shell"],
            ["gunicorn", "config.wsgi"],
        ):
            with self.subTest(argv=argv):
                self.assertFalse(running_tests(argv))

    def test_the_fast_hasher_is_actually_in_effect_while_testing(self):
        """判定与赋值之间没有断链：测试进程里真的换成了 MD5。"""
        self.assertEqual(
            settings.PASSWORD_HASHERS,
            ["django.contrib.auth.hashers.MD5PasswordHasher"],
        )


def _in_site_packages(path):
    """第三方件的判据：路径里出现过这两个目录名（virtualenv 与系统安装都用它们）。"""
    return bool({"site-packages", "dist-packages"} & set(path.parts))


class AppLoggerTests(SimpleTestCase):
    """每个自家包都配了 logger，而且真的写到 ``logs/django.log``。

    样本量两头钉：一头是**仓库里实际有哪些包**（按安装位置现场数：在 ``BASE_DIR``
    之下、不在 site-packages 里——``.venv`` 就在根下，只判「在 BASE_DIR 之下」会把
    site-packages 里的 app 全收进来），另一头是下面这份**显式清单**。检测规则变哑、
    或包增删了而清单没跟上，`test_the_package_list_matches_the_repo` 都会红。

    ``config`` 不是 app（没有 ``AppConfig``），但它发的 `request.start` / `request.end`
    正是诊断路径要翻的那几行，所以同样在清单里。
    """

    #: 自家包。**新增一个包要同时改这里与 `settings.LOGGING["loggers"]`。**
    EXPECTED_PACKAGES = (
        "accounts",
        "notices",
        "media",
        "content",
        "config",
        "projects",
        "competitions",
        "reviews",
        "equipment",
        "discussion",
        "core",
    )

    def repo_package_names(self):
        base = Path(settings.BASE_DIR).resolve()
        names = {
            config.name
            for config in apps.get_app_configs()
            if not _in_site_packages(path := Path(config.path).resolve())
            and path.is_relative_to(base)
        }
        names.add("config")
        return names

    def test_the_package_list_matches_the_repo(self):
        """清单与仓库对得上——检测规则失效、或新增／改名了包，这条先红。"""
        self.assertEqual(self.repo_package_names(), set(self.EXPECTED_PACKAGES))

    def test_every_own_package_is_listed_in_the_logging_config(self):
        loggers = settings.LOGGING["loggers"]

        for name in self.EXPECTED_PACKAGES:
            with self.subTest(package=name):
                self.assertIn(
                    name,
                    loggers,
                    f"{name} 没有自己的 logger：它的 info 不落盘、warning 只到 stderr",
                )
                self.assertTrue(loggers[name]["handlers"])

    def test_every_own_package_logger_is_actually_wired_to_the_log_file(self):
        """dictConfig 真的执行过了：生效级别不是 WARNING，且挂着日志文件的 handler。"""
        log_file = Path(settings.LOG_DIR, "django.log")

        for name in self.EXPECTED_PACKAGES:
            with self.subTest(package=name):
                logger = logging.getLogger(name)
                self.assertLess(
                    logger.getEffectiveLevel(),
                    logging.WARNING,
                    f"{name} 的生效级别是 WARNING：logger.info 会在级别检查处被丢掉",
                )

                file_handlers = [
                    handler
                    for handler in logger.handlers
                    if isinstance(handler, logging.handlers.RotatingFileHandler)
                    and Path(handler.baseFilename) == log_file
                ]
                self.assertTrue(
                    file_handlers,
                    f"{name} 没挂上 {log_file} 的 handler：日志出不了进程",
                )

    def test_a_record_from_every_own_package_logger_lands_in_the_file(self):
        """端到端：真发一条 INFO，真去文件里找它。

        上面那条只看接线（结构），handler 级别被抬到 ERROR、或格式化时吞掉记录，
        它照样绿——这条才是「日志写进日志文件」本身。
        """
        log_file = Path(settings.LOG_DIR, "django.log")
        marker = f"app-logger-probe-{uuid4().hex}"
        start = log_file.stat().st_size

        for name in self.EXPECTED_PACKAGES:
            logging.getLogger(name).info("%s %s", marker, name)

        with log_file.open(encoding="utf-8") as handle:
            handle.seek(start)
            appended = handle.read()

        for name in self.EXPECTED_PACKAGES:
            with self.subTest(package=name):
                self.assertIn(f"{marker} {name}", appended)


class SecurityHeadersTests(TestCase):
    """安全响应头真的发出去了——中间件挂在 settings 里才作数。"""

    def test_csp_is_enforced_and_locks_the_important_sources(self):
        response = self.client.get(reverse("accounts:home"))

        policy = response.headers.get("Content-Security-Policy")
        self.assertIsNotNone(policy, "CSP 没发出去：中间件是不是没挂进 MIDDLEWARE？")

        # 强制模式：不再带 Report-Only 那个后缀，浏览器会真的拦下来。
        self.assertNotIn("Content-Security-Policy-Report-Only", response.headers)

        self.assertIn("default-src 'self'", policy)
        self.assertIn("frame-ancestors 'none'", policy)
        self.assertIn("object-src 'none'", policy)
        # 前台**不能**出现 unsafe-inline：有了它，这条 CSP 对 XSS 基本就白设了。
        # 全站的资源都自托管，没有理由放行内联。
        self.assertNotIn("unsafe-inline", policy)

    def test_admin_gets_a_relaxed_policy(self):
        """后台单独放宽——Django admin 的模板自带内联脚本与内联样式，收不掉。

        这一条不是「后台可以随便」，而是把放宽**限定在后台**：前台的策略仍然
        不含 unsafe-inline（上一个用例钉着它）。
        """
        response = self.client.get("/admin/login/")

        policy = response.headers.get("Content-Security-Policy", "")
        self.assertIn("'unsafe-inline'", policy)
        # 放宽的只有那两处，别的一条都没松。
        self.assertIn("frame-ancestors 'none'", policy)
        self.assertIn("object-src 'none'", policy)

    def test_permissions_policy_turns_off_unused_features(self):
        response = self.client.get(reverse("accounts:home"))

        self.assertIn(
            "camera=()",
            response.headers.get("Permissions-Policy", ""),
        )

    def test_headers_do_not_override_what_a_view_already_set(self):
        """视图自己发过的头不被覆盖：setdefault 而不是赋值。"""
        response = self.client.get(reverse("accounts:home"))
        response["Content-Security-Policy"] = "default-src 'none'"

        middleware = SecurityHeadersMiddleware(lambda request: response)
        result = middleware(response.wsgi_request)

        self.assertEqual(result["Content-Security-Policy"], "default-src 'none'")
