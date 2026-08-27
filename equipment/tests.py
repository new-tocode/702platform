"""Acceptance tests for equipment inventory, borrowing, returning and permissions."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

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
