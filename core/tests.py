"""Core registry and audit acceptance tests."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .audit import record_audit
from .models import AuditLog
from .registry import (
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
                "equipment.borrow",
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

        response = self.client.get(reverse("accounts:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "审计日志")
        self.assertContains(response, reverse("admin:core_auditlog_changelist"))

    def test_member_home_renders_registered_operation_cards(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "设备借用")
        self.assertContains(response, "借用记录")
        self.assertContains(response, "项目组")
        self.assertNotContains(response, "竞赛报名")

    def tearDown(self):
        # Remove test-only entries while keeping AppConfig registrations intact
        # for the next test in this process.
        unregister_entry("test.first")
        unregister_entry("test.second")


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
