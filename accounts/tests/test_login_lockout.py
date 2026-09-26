"""登录失败锁定（axes）：账号与 IP 各算各的，解锁后能再登。"""

import json

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import AuditLog


User = get_user_model()


class LoginLockoutAcceptanceTests(TestCase):
    """登录失败到一定次数就锁，而且锁上之后**正确的口令也进不来**。

    这条是整道防线的关键。如果锁定只是一句提示、后端照样校验口令，那它挡不住
    任何人——攻击者撞对的那一次正好会成功登录。所以下面的用例里，第 N 次尝试
    用的是**正确口令**，期望仍然是拒绝。

    阈值与维度取自 settings（当前 10 次、账号与 IP 各算各的），这里不写死数字，
    免得改配置时测试变成假绿。
    """

    def setUp(self):
        from axes.models import AccessAttempt

        AccessAttempt.objects.all().delete()
        self.user = User.objects.create_user(
            username="lockout-member",
            password="Correct-Password-123!",
        )
        self.user.must_change_password = False
        self.user.save(update_fields=["must_change_password"])
        self.limit = settings.AXES_FAILURE_LIMIT

    def tearDown(self):
        from axes.models import AccessAttempt

        AccessAttempt.objects.all().delete()

    def _attempt(self, password):
        return self.client.post(
            reverse("accounts:login"),
            {"username": self.user.username, "password": password},
            # 每次都换一个 REMOTE_ADDR，把「账号维度」单独隔出来测：否则 IP 那一格
            # 会先满，测到的就不是账号锁定了。
            REMOTE_ADDR=f"10.0.0.{self._ip()}",
        )

    _counter = 0

    def _ip(self):
        type(self)._counter += 1
        return (type(self)._counter % 200) + 1

    def test_correct_password_is_refused_once_locked(self):
        for _ in range(self.limit):
            self._attempt("definitely-wrong")

        response = self._attempt("Correct-Password-123!")

        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertNotEqual(response.status_code, 302)

    def test_lockout_response_says_so_in_chinese(self):
        for _ in range(self.limit):
            self._attempt("definitely-wrong")

        response = self._attempt("definitely-wrong")

        self.assertContains(response, "登录尝试次数过多", status_code=403)

    def test_failures_below_the_limit_still_allow_a_correct_login(self):
        for _ in range(self.limit - 1):
            self._attempt("definitely-wrong")

        response = self._attempt("Correct-Password-123!")

        self.assertEqual(response.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)

    def test_successful_login_does_not_clear_the_ip_counter(self):
        """成功登一次不该把 IP 那一格刷掉。

        否则一个已经知道口令的攻击者可以「错几次、登一次」地循环，把 IP 计数永远
        压在阈值之下——这道防线就等于没有。用例直接盯住「第一条失败记录还在」。
        """
        from axes.models import AccessAttempt

        for _ in range(self.limit - 1):
            self._attempt("definitely-wrong")
        failures_before = AccessAttempt.objects.filter(
            failures_since_start__gt=0
        ).count()
        self.assertGreater(failures_before, 0, "前置条件：应当已有失败记录")

        self._attempt("Correct-Password-123!")

        self.assertEqual(
            AccessAttempt.objects.filter(failures_since_start__gt=0).count(),
            failures_before,
            "成功登录把之前那几格的失败计数清掉了",
        )

    def test_lockout_writes_an_audit_record(self):
        for _ in range(self.limit):
            self._attempt("definitely-wrong")

        self.assertTrue(
            AuditLog.objects.filter(action="accounts.login.lockout").exists(),
            "锁定没有留下审计记录",
        )

    def test_lockout_audit_never_records_the_password(self):
        for _ in range(self.limit):
            self._attempt("Super-Secret-Guess-999")

        for entry in AuditLog.objects.filter(action="accounts.login.lockout"):
            self.assertNotIn("Super-Secret-Guess-999", json.dumps(entry.detail))
