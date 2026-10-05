"""登录失败锁定（axes）：账号与 IP 各算各的，解锁后能再登。"""

import json

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import AuditLog


User = get_user_model()


@override_settings(TRUST_FORWARDED_FOR=True)
class LoginLockoutAcceptanceTests(TestCase):
    """登录失败到一定次数就锁，而且锁上之后**正确的口令也进不来**。

    这条是整道防线的关键。如果锁定只是一句提示、后端照样校验口令，那它挡不住
    任何人——攻击者撞对的那一次正好会成功登录。所以下面的用例里，第 N 次尝试
    用的是**正确口令**，期望仍然是拒绝。

    阈值与维度取自 settings（当前 10 次、账号与 IP 各算各的），这里不写死数字，
    免得改配置时测试变成假绿。

    **请求形状照生产来**：线上是 nginx 反代，``REMOTE_ADDR`` 恒为 127.0.0.1，
    真实来源在 ``X-Forwarded-For`` 里。过去这里靠换 ``REMOTE_ADDR`` 来区分客户端，
    等于在测一个线上不存在的部署——测试一直是绿的，而线上所有请求共用同一个 IP
    桶。所以下面固定 ``REMOTE_ADDR=127.0.0.1``、改 ``X-Forwarded-For``，
    并打开 ``TRUST_FORWARDED_FOR``（与 ``env.sh`` 一致）。
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

    def _attempt(self, password, *, ip=None, username=None):
        return self.client.post(
            reverse("accounts:login"),
            {"username": username or self.user.username, "password": password},
            # 每次都换一个来源 IP，把「账号维度」单独隔出来测：否则 IP 那一格
            # 会先满，测到的就不是账号锁定了。
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR=ip or f"10.0.0.{self._ip()}",
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


@override_settings(TRUST_FORWARDED_FOR=True)
class LockoutBucketsArePerClientTests(TestCase):
    """不同来源 IP 各算各的——一个 IP 的失败不该把别人牵连进来。

    这是反向代理下最容易踩坏的一格。取不到真实 IP 时（每个请求都记成
    127.0.0.1），全站共用一个 IP 桶，两个方向同时坏掉：

    * **拒绝服务**：任意 10 次失败就让所有人 30 分钟内登不进来，触发成本是
      10 个请求，且可以反复触发；
    * **防爆破失效**：分布式爆破（很多 IP 各试几次）在 IP 维度上完全不计入。

    下面两个用例分别盯住这两面：别的 IP 的失败不牵连本 IP；同一个 IP 连错到
    阈值仍然会被锁。
    """

    def setUp(self):
        from axes.models import AccessAttempt

        AccessAttempt.objects.all().delete()
        self.user = User.objects.create_user(
            username="bucket-member",
            password="Correct-Password-123!",
        )
        self.user.must_change_password = False
        self.user.save(update_fields=["must_change_password"])
        self.limit = settings.AXES_FAILURE_LIMIT

    def tearDown(self):
        from axes.models import AccessAttempt

        AccessAttempt.objects.all().delete()

    def _attempt(self, *, password, ip, username):
        # 固定 REMOTE_ADDR、只变 X-Forwarded-For：这正是生产的形状。
        return self.client.post(
            reverse("accounts:login"),
            {"username": username, "password": password},
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR=ip,
        )

    def test_failures_from_other_ips_do_not_lock_a_third_one(self):
        # 两个 IP 各错几次，合计已经超过阈值，但各自都没到。
        per_ip = max(self.limit - 4, 1)
        for index in range(per_ip):
            self._attempt(
                password="definitely-wrong",
                ip="10.1.0.1",
                username=f"probe-a-{index}",
            )
        for index in range(per_ip):
            self._attempt(
                password="definitely-wrong",
                ip="10.1.0.2",
                username=f"probe-b-{index}",
            )

        response = self._attempt(
            password="Correct-Password-123!",
            ip="10.1.0.3",
            username=self.user.username,
        )

        self.assertEqual(
            response.status_code,
            302,
            "第三个 IP 被别的 IP 的失败锁住了：IP 维度退化成了全站共用一个桶",
        )

    def test_same_ip_is_still_locked_at_the_threshold(self):
        for index in range(self.limit):
            self._attempt(
                password="definitely-wrong",
                ip="10.2.0.9",
                username=f"probe-c-{index}",
            )

        response = self._attempt(
            password="Correct-Password-123!",
            ip="10.2.0.9",
            username=self.user.username,
        )

        self.assertEqual(
            response.status_code,
            403,
            "同一个 IP 连错到阈值却没有被锁——限速这道闸门没生效",
        )
