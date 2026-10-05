"""操作入口注册表与审计日志：入口按权限过滤，审计只读。"""

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from ..audit import get_client_ip, record_audit
from ..models import AuditLog
from ..registry import (
    get_entries_for_user,
    get_registered_entries,
    register_entry,
    unregister_entry,
)


User = get_user_model()


class OperationRegistryAcceptanceTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="registry-admin",
            password="Admin-Password-123!",
        )
        self.user = User.objects.create_user(
            username="registry-member",
            password="Member-Password-123!",
        )
        self.user.must_change_password = False
        self.user.save(update_fields=["must_change_password"])

    def test_apps_register_expected_entries(self):
        keys = {entry.key for entry in get_registered_entries()}

        self.assertEqual(
            keys,
            {
                "accounts.profile",
                "accounts.password",
                "notices.internal",
                "projects.groups",
                "competitions.registration",
                "reviews.queue",
                "equipment.borrow",
                "equipment.records",
                "core.audit",
            },
        )

    def test_registry_filters_forced_users_and_permission_aware_entries(self):
        visible_keys = {entry.key for entry in get_entries_for_user(self.user)}
        self.assertEqual(
            visible_keys,
            {
                "accounts.profile",
                "accounts.password",
                "notices.internal",
                "projects.groups",
                "competitions.registration",
                "equipment.records",
            },
        )

        self.user.must_change_password = True
        self.user.save(update_fields=["must_change_password"])
        self.assertEqual(get_entries_for_user(self.user), ())

    def test_registry_is_idempotent_and_orders_entries(self):
        register_entry(
            key="test.first",
            label="测试一",
            description="",
            url_name="accounts:home",
            sort_order=1,
        )
        register_entry(
            key="test.first",
            label="更新后的测试一",
            description="",
            url_name="accounts:home",
            sort_order=1,
        )
        register_entry(
            key="test.second",
            label="测试二",
            description="",
            url_name="accounts:home",
            sort_order=2,
        )

        entries = get_registered_entries()
        test_entries = [entry for entry in entries if entry.key.startswith("test.")]
        self.assertEqual([entry.key for entry in test_entries], ["test.first", "test.second"])
        self.assertEqual(test_entries[0].label, "更新后的测试一")

    def test_admin_sees_registered_audit_entry(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "审计日志")
        self.assertContains(response, reverse("admin:core_auditlog_changelist"))

    def test_admin_backend_link_is_visible_to_staff_member(self):
        staff = User.objects.create_user(
            username="registry-staff",
            password="Staff-Password-123!",
        )
        staff.is_staff = True
        staff.must_change_password = False
        staff.save(update_fields=["is_staff", "must_change_password"])

        self.client.force_login(staff)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("admin:index"))
        self.assertContains(response, "管理后台")

    def test_admin_backend_link_is_hidden_from_regular_member(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse("admin:index"))
        self.assertNotContains(response, "管理后台")

    def test_member_home_renders_registered_operation_cards(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "借用记录")
        self.assertContains(response, "项目组")
        self.assertContains(response, "竞赛信息")
        # A member with no project group cannot see the borrowing entry.
        self.assertNotContains(response, "设备借用")

    def tearDown(self):
        # Remove test-only entries while keeping AppConfig registrations intact
        # for the next test in this process.
        unregister_entry("test.first")
        unregister_entry("test.second")


class ClientIpResolutionTests(TestCase):
    """取来源 IP 的口径：默认不信转发头，配了可信代理才信，且只信最后一段。

    这一格关系两件事：审计日志里「是谁」能不能回答，以及 axes 的按 IP 锁定会不会
    把全站算成同一个人。默认值必须站在「不信」那一侧——客户端可以随便发
    X-Forwarded-For，没配代理的部署不该被它牵着走。
    """

    def setUp(self):
        self.factory = RequestFactory()

    def _request(self, *, remote_addr="127.0.0.1", forwarded=None):
        extra = {"REMOTE_ADDR": remote_addr}
        if forwarded is not None:
            extra["HTTP_X_FORWARDED_FOR"] = forwarded
        return self.factory.get("/", **extra)

    def test_without_the_switch_the_header_is_ignored(self):
        request = self._request(forwarded="1.2.3.4")
        self.assertEqual(get_client_ip(request), "127.0.0.1")

    @override_settings(TRUST_FORWARDED_FOR=True)
    def test_with_the_switch_the_header_is_used(self):
        request = self._request(forwarded="203.0.113.9")
        self.assertEqual(get_client_ip(request), "203.0.113.9")

    @override_settings(TRUST_FORWARDED_FOR=True)
    def test_the_last_hop_wins_so_a_client_cannot_spoof_the_front(self):
        # 客户端自己塞的 1.2.3.4 落在前面，nginx 追加/覆写的对端地址在最后。
        request = self._request(forwarded="1.2.3.4, 203.0.113.9")
        self.assertEqual(get_client_ip(request), "203.0.113.9")

    @override_settings(TRUST_FORWARDED_FOR=True)
    def test_empty_header_falls_back_to_remote_addr(self):
        request = self._request(forwarded="")
        self.assertEqual(get_client_ip(request), "127.0.0.1")

    def test_no_request_is_none(self):
        self.assertIsNone(get_client_ip(None))


class AuditLogAcceptanceTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="audit-admin",
            password="Admin-Password-123!",
        )

    def test_record_audit_persists_actor_target_request_and_safe_detail(self):
        audit = record_audit(
            action="test.action",
            user=self.admin,
            target=self.admin,
            detail={"field": "value", "count": 1},
        )

        audit.refresh_from_db()
        self.assertEqual(audit.user, self.admin)
        self.assertEqual(audit.target_type, "accounts.user")
        self.assertEqual(audit.target_id, str(self.admin.pk))
        self.assertEqual(audit.request_id, "")
        self.assertEqual(audit.detail, {"field": "value", "count": 1})
        self.assertEqual(AuditLog.objects.count(), 1)

    def test_audit_admin_is_read_only(self):
        from django.contrib.admin import site

        model_admin = site._registry[AuditLog]
        self.assertFalse(model_admin.has_add_permission(None))
        self.assertFalse(model_admin.has_change_permission(None))
        self.assertFalse(model_admin.has_delete_permission(None))
