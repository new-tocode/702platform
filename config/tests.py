"""settings 里的判定逻辑单测。

目前只有一条：快速口令哈希只该在测试进程生效。它守着一道安全线——判定写坏
（比如只认 ``sys.argv[1]``，碰上 ``manage.py --settings=x test`` 就漏了）会让生产
静默落到弱哈希上，没有任何报错，所以单独钉住。
"""

from django.conf import settings
from django.test import SimpleTestCase

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
