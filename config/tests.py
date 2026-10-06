"""settings 里的判定逻辑单测。

目前只有一条：快速口令哈希只该在测试进程生效。它守着一道安全线——判定写坏
（比如只认 ``sys.argv[1]``，碰上 ``manage.py --settings=x test`` 就漏了）会让生产
静默落到弱哈希上，没有任何报错，所以单独钉住。
"""

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
