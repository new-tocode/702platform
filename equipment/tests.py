"""Acceptance tests for equipment inventory, borrowing, returning and permissions."""

import threading
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog

from .models import Equipment, EquipmentBorrow
from .services import BorrowAlreadyReturned, EquipmentUnavailable, create_borrow, return_borrow


User = get_user_model()


class EquipmentAcceptanceTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="equipment-admin",
            password="Admin-Password-123!",
        )
        self.member = User.objects.create_user(
            username="equipment-member",
            password="Member-Password-123!",
        )
        self.member.must_change_password = False
        self.member.save(update_fields=["must_change_password"])
        self.other_member = User.objects.create_user(
            username="equipment-other-member",
            password="Other-Member-123!",
        )
        self.other_member.must_change_password = False
        self.other_member.save(update_fields=["must_change_password"])
        self.equipment = Equipment.objects.create(
            name="开发笔记本",
            category="计算设备",
            total_count=2,
            available_count=2,
            description="用于竞赛开发。",
            is_active=True,
        )
        self.inactive_equipment = Equipment.objects.create(
            name="维修中设备",
            category="测试",
            total_count=1,
            available_count=1,
            is_active=False,
        )

    def borrow_data(self, **overrides):
        data = {
            "planned_return_date": (timezone.localdate() + timedelta(days=3)).isoformat(),
            "remark": "用于项目开发。",
        }
        data.update(overrides)
        return data

    def test_logged_in_member_can_view_active_equipment_only(self):
        self.client.force_login(self.member)

        response = self.client.get(reverse("equipment:list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.equipment.name)
        self.assertNotContains(response, self.inactive_equipment.name)
        self.assertContains(response, "2 / 2")

    def test_anonymous_cannot_view_or_borrow_equipment(self):
        list_response = self.client.get(reverse("equipment:list"))
        borrow_response = self.client.get(
            reverse("equipment:borrow", args=(self.equipment.pk,))
        )

        self.assertEqual(list_response.status_code, 302)
        self.assertEqual(borrow_response.status_code, 302)
        self.assertIn(reverse("accounts:login"), list_response["Location"])

    def test_member_borrow_decrements_available_count_and_creates_record(self):
        self.client.force_login(self.member)

        response = self.client.post(
            reverse("equipment:borrow", args=(self.equipment.pk,)),
            self.borrow_data(),
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("equipment_borrows:list"))
        self.equipment.refresh_from_db()
        borrow = EquipmentBorrow.objects.get()
        self.assertEqual(self.equipment.available_count, 1)
        self.assertEqual(borrow.borrower, self.member)
        self.assertEqual(borrow.equipment, self.equipment)
        self.assertEqual(borrow.status, EquipmentBorrow.BORROWED)
        self.assertIsNone(borrow.actual_return_date)
        audit = AuditLog.objects.get(action="equipment.borrow")
        self.assertEqual(audit.user, self.member)
        self.assertEqual(audit.target_id, str(borrow.pk))

    def test_out_of_stock_equipment_cannot_be_borrowed(self):
        self.equipment.available_count = 0
        self.equipment.save(update_fields=["available_count"])
        self.client.force_login(self.member)

        response = self.client.post(
            reverse("equipment:borrow", args=(self.equipment.pk,)),
            self.borrow_data(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "当前没有可借数量")
        self.assertFalse(EquipmentBorrow.objects.exists())
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.available_count, 0)

    def test_inactive_equipment_cannot_be_borrowed_by_url(self):
        self.client.force_login(self.member)

        response = self.client.get(
            reverse("equipment:borrow", args=(self.inactive_equipment.pk,))
        )

        self.assertEqual(response.status_code, 404)

    def test_planned_return_date_cannot_be_before_today(self):
        self.client.force_login(self.member)

        response = self.client.post(
            reverse("equipment:borrow", args=(self.equipment.pk,)),
            self.borrow_data(
                planned_return_date=(timezone.localdate() - timedelta(days=1)).isoformat()
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "计划归还日期不能早于今天")
        self.assertFalse(EquipmentBorrow.objects.exists())

    def test_member_can_only_view_own_borrows(self):
        own_borrow = create_borrow(
            equipment_id=self.equipment.pk,
            borrower=self.member,
            planned_return_date=timezone.localdate() + timedelta(days=2),
            remark="本人记录",
            actor=self.member,
        )
        other_equipment = Equipment.objects.create(
            name="备用键盘",
            total_count=1,
            available_count=1,
        )
        other_borrow = create_borrow(
            equipment_id=other_equipment.pk,
            borrower=self.other_member,
            planned_return_date=timezone.localdate() + timedelta(days=2),
            remark="他人记录",
            actor=self.other_member,
        )
        self.client.force_login(self.member)

        response = self.client.get(reverse("equipment_borrows:list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, own_borrow.equipment.name)
        self.assertNotContains(response, other_borrow.equipment.name)
        self.assertNotContains(response, "他人记录")

    def test_member_return_restores_available_count_and_actual_return_date(self):
        borrow = create_borrow(
            equipment_id=self.equipment.pk,
            borrower=self.member,
            planned_return_date=timezone.localdate() + timedelta(days=2),
            remark="待归还",
            actor=self.member,
        )
        self.client.force_login(self.member)

        response = self.client.post(
            reverse("equipment_borrows:return", args=(borrow.pk,))
        )

        self.assertEqual(response.status_code, 302)
        borrow.refresh_from_db()
        self.equipment.refresh_from_db()
        self.assertEqual(borrow.status, EquipmentBorrow.RETURNED)
        self.assertEqual(borrow.actual_return_date, timezone.localdate())
        self.assertEqual(self.equipment.available_count, 2)

    def test_member_cannot_return_someone_elses_borrow(self):
        borrow = create_borrow(
            equipment_id=self.equipment.pk,
            borrower=self.other_member,
            planned_return_date=timezone.localdate() + timedelta(days=2),
            remark="他人借用",
            actor=self.other_member,
        )
        self.client.force_login(self.member)

        response = self.client.post(
            reverse("equipment_borrows:return", args=(borrow.pk,))
        )

        self.assertEqual(response.status_code, 404)
        borrow.refresh_from_db()
        self.assertEqual(borrow.status, EquipmentBorrow.BORROWED)

    def test_admin_can_view_all_borrows_and_return_for_member(self):
        borrow = create_borrow(
            equipment_id=self.equipment.pk,
            borrower=self.member,
            planned_return_date=timezone.localdate() + timedelta(days=2),
            remark="管理员代归还",
            actor=self.member,
        )
        self.client.force_login(self.admin)

        list_response = self.client.get(reverse("equipment_borrows:list"))
        return_response = self.client.post(
            reverse("equipment_borrows:return", args=(borrow.pk,))
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, self.member.username)
        self.assertEqual(return_response.status_code, 302)
        borrow.refresh_from_db()
        self.assertEqual(borrow.status, EquipmentBorrow.RETURNED)

    def test_second_return_does_not_restore_inventory_twice(self):
        borrow = create_borrow(
            equipment_id=self.equipment.pk,
            borrower=self.member,
            planned_return_date=timezone.localdate() + timedelta(days=2),
            remark="重复归还测试",
            actor=self.member,
        )
        return_borrow(borrow_id=borrow.pk, actor=self.member)
        self.equipment.refresh_from_db()
        available_after_first_return = self.equipment.available_count

        with self.assertRaises(BorrowAlreadyReturned):
            return_borrow(borrow_id=borrow.pk, actor=self.member)

        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.available_count, available_after_first_return)
        self.assertEqual(self.equipment.available_count, self.equipment.total_count)

    def test_equipment_inventory_constraints_reject_invalid_values(self):
        invalid_equipment = Equipment(
            name="无效库存",
            total_count=1,
            available_count=2,
        )

        with self.assertRaises(ValidationError):
            invalid_equipment.save()

    def test_total_count_cannot_be_reduced_below_available_and_borrowed_units(self):
        create_borrow(
            equipment_id=self.equipment.pk,
            borrower=self.member,
            planned_return_date=timezone.localdate() + timedelta(days=2),
            remark="库存约束测试",
            actor=self.member,
        )
        self.equipment.refresh_from_db()
        self.equipment.total_count = 1

        with self.assertRaises(ValidationError) as context:
            self.equipment.save()

        self.assertIn("设备总量不能小于", str(context.exception))

    def test_borrow_record_constraints_reject_invalid_status_dates(self):
        with self.assertRaises(ValidationError):
            EquipmentBorrow.objects.create(
                equipment=self.equipment,
                borrower=self.member,
                borrow_date=timezone.localdate(),
                planned_return_date=timezone.localdate() + timedelta(days=1),
                status=EquipmentBorrow.RETURNED,
            )

        with self.assertRaises(ValidationError):
            EquipmentBorrow.objects.create(
                equipment=self.equipment,
                borrower=self.member,
                borrow_date=timezone.localdate(),
                planned_return_date=timezone.localdate() + timedelta(days=1),
                status=EquipmentBorrow.RETURNED,
                actual_return_date=timezone.localdate() - timedelta(days=1),
            )

    def test_admin_can_manage_equipment_and_regular_member_cannot(self):
        self.client.force_login(self.admin)
        admin_response = self.client.get("/admin/equipment/equipment/")
        self.assertEqual(admin_response.status_code, 200)

        self.client.force_login(self.member)
        member_response = self.client.get("/admin/equipment/equipment/")
        self.assertEqual(member_response.status_code, 302)


@skipUnlessDBFeature("has_select_for_update")
class ConcurrentEquipmentBorrowTests(TransactionTestCase):
    """并发借用：验证 select_for_update 行锁防止库存超借。

    本类只在支持行级锁的后端运行（PostgreSQL）。SQLite 的
    has_select_for_update 为 False，Django 会静默剥离 FOR UPDATE 子句
    （见 django/db/models/sql/compiler.py），并发语义退化为整库写锁，
    因此这类场景必须用 PostgreSQL 才能覆盖。
    """

    def setUp(self):
        self.member_a = User.objects.create_user(
            username="concurrent-member-a",
            password="Concurrent-A-123!",
        )
        self.member_b = User.objects.create_user(
            username="concurrent-member-b",
            password="Concurrent-B-123!",
        )
        self.equipment = Equipment.objects.create(
            name="并发争抢设备",
            category="测试",
            total_count=1,
            available_count=1,
        )

    def borrow(self, user):
        return create_borrow(
            equipment_id=self.equipment.pk,
            borrower=user,
            planned_return_date=timezone.localdate() + timedelta(days=3),
            remark="并发测试",
            actor=user,
        )

    def test_borrow_service_acquires_row_lock(self):
        """create_borrow 发出的 SQL 必须带 FOR UPDATE 行锁子句。"""
        with CaptureQueriesContext(connection) as captured:
            self.borrow(self.member_a)

        statements = [query["sql"].upper() for query in captured.captured_queries]
        self.assertTrue(
            any("FOR UPDATE" in statement for statement in statements),
            msg=f"未发现 FOR UPDATE 行锁，实际 SQL: {statements}",
        )

    def test_concurrent_borrow_does_not_oversubscribe(self):
        """两个并发请求争抢最后一件设备时，只能有一个成功。"""
        outcome = []
        errors = []
        barrier = threading.Barrier(2)

        def attempt(user):
            try:
                barrier.wait(timeout=10)  # 让两个线程尽量同时发起借用
                self.borrow(user)
                outcome.append("borrowed")
            except EquipmentUnavailable:
                outcome.append("unavailable")
            except Exception as exc:  # noqa: BLE001 - 收集后在主线程断言
                errors.append(f"{type(exc).__name__}: {exc}")
            finally:
                # 线程内的连接不会自动回收，显式关闭避免泄漏
                connection.close()

        threads = [
            threading.Thread(target=attempt, args=(user,))
            for user in (self.member_a, self.member_b)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertEqual(errors, [], msg=f"并发借用出现异常: {errors}")
        self.assertEqual(
            sorted(outcome),
            ["borrowed", "unavailable"],
            msg=f"期望恰好一个成功、一个库存不足，实际: {outcome}",
        )

        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.available_count, 0)
        self.assertEqual(
            EquipmentBorrow.objects.filter(
                equipment=self.equipment,
                status=EquipmentBorrow.BORROWED,
            ).count(),
            1,
        )
