"""个人资料页：字段排布与校验，以及他人可见的只读资料页。"""

import re

from django import forms
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from ..forms import ProfileForm


User = get_user_model()

class ProfilePageAcceptanceTests(TestCase):
    """个人信息页的排布：一行两项、手机号收窄并前移、个人简介压轴。"""

    def setUp(self):
        self.user = User.objects.create_user(
            username="profile-member",
            password="Member-Password-123!",
        )
        self.user.must_change_password = False
        self.user.save(update_fields=["must_change_password"])
        self.client.force_login(self.user)

    def cells(self):
        """表单给出的排布：按行摊平成一格一格。"""
        return [cell for row in ProfileForm().rows() for cell in row]

    def test_name_pairs_with_student_id_and_college_with_major(self):
        rows = [
            [cell["field"].name for cell in row] for row in ProfileForm().rows()
        ]

        self.assertEqual(rows[0], ["full_name", "student_id"])
        self.assertEqual(rows[1], ["college", "major"])

    def test_phone_is_the_only_narrow_field_and_comes_before_specialty(self):
        names = [cell["field"].name for cell in self.cells()]

        self.assertEqual(
            [cell["field"].name for cell in self.cells() if cell["narrow"]],
            ["phone"],
        )
        self.assertLess(names.index("phone"), names.index("specialty"))

    def test_specialty_stays_a_single_line_input(self):
        widget = ProfileForm().fields["specialty"].widget

        self.assertIsInstance(widget, forms.TextInput)

    def test_bio_is_last_and_renders_as_a_tall_textarea(self):
        cells = self.cells()

        self.assertEqual(cells[-1]["field"].name, "bio")
        response = self.client.get(reverse("accounts:profile"))
        self.assertContains(response, '<textarea name="bio"')
        self.assertContains(response, 'rows="8"')

    def test_profile_page_pairs_name_with_student_id_in_one_row(self):
        response = self.client.get(reverse("accounts:profile"))

        html = response.content.decode()
        first_row = re.search(r'<div class="field-row">(.*?)</div>\s*</div>', html, re.S)
        self.assertIn('name="full_name"', first_row.group(1))
        self.assertIn('name="student_id"', first_row.group(1))

    def test_no_template_comment_leaks_onto_the_page(self):
        # Django 的 {# #} 不跨行：写成两行会把注释当正文渲染出来，页面上直接可见。
        response = self.client.get(reverse("accounts:profile"))

        self.assertNotIn("{#", response.content.decode())

    def test_profile_page_marks_single_field_rows_as_full_width(self):
        response = self.client.get(reverse("accounts:profile"))

        html = response.content.decode()
        # 两行两项，手机号、特长、其他联系方式、个人简介各占一行。
        self.assertEqual(html.count('class="field-row"'), 6)
        # 独占一行的字段横跨两列：特长仍是整幅的单行输入，个人简介的框也只受这一处约束。
        self.assertEqual(html.count('class="field field-full"'), 3)
        self.assertIn('class="field field-full field-short"', html)

    def test_member_can_save_a_bio(self):
        response = self.client.post(
            reverse("accounts:profile"),
            {
                "full_name": "成员一",
                "student_id": "20260001",
                "college": "计算机学院",
                "major": "软件工程",
                "phone": "13800000000",
                "specialty": "算法设计",
                "contact": "",
                "bio": "喜欢做机器人，也写一点前端。",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.bio, "喜欢做机器人，也写一点前端。")

    def test_bio_longer_than_the_limit_is_rejected(self):
        response = self.client.post(
            reverse("accounts:profile"),
            {"bio": "字" * 1001},
        )

        self.assertEqual(response.status_code, 200)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.bio, "")


class ReadOnlyMemberProfileAcceptanceTests(TestCase):
    def setUp(self):
        self.viewer = User.objects.create_user(
            username="profile-viewer",
            password="Member-Password-123!",
        )
        self.viewer.must_change_password = False
        self.viewer.save(update_fields=["must_change_password"])
        self.member = User.objects.create_user(
            username="profile-target",
            email="private@example.com",
            password="Member-Password-123!",
        )
        self.member.must_change_password = False
        self.member.save(update_fields=["must_change_password"])
        self.member.profile.full_name = "Rin Chen"
        self.member.profile.student_id = "STUDENT-SECRET-91"
        self.member.profile.college = "Engineering"
        self.member.profile.major = "Robotics"
        self.member.profile.specialty = "Embedded systems"
        self.member.profile.bio = "Builds small robots."
        self.member.profile.phone = "13800000000"
        self.member.profile.contact = "WeChat: rinchen"
        self.member.profile.save()

    def test_member_can_view_approved_read_only_profile_fields(self):
        self.client.force_login(self.viewer)

        response = self.client.get(
            reverse("accounts:member_profile", args=(self.member.pk,))
        )

        self.assertEqual(response.status_code, 200)
        for visible_value in (
            "Rin Chen",
            "profile-target",
            "Engineering",
            "Robotics",
            "Embedded systems",
            "Builds small robots.",
            "13800000000",
            "WeChat: rinchen",
        ):
            with self.subTest(value=visible_value):
                self.assertContains(response, visible_value)
        self.assertNotContains(response, "STUDENT-SECRET-91")
        self.assertNotContains(response, "private@example.com")
        self.assertNotContains(response, 'name="phone"')
        self.assertNotContains(response, 'name="bio"')

    def test_profile_page_uses_account_name_when_member_has_no_name(self):
        self.member.profile.full_name = ""
        self.member.profile.save(update_fields=["full_name"])
        self.client.force_login(self.viewer)

        response = self.client.get(
            reverse("accounts:member_profile", args=(self.member.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "profile-target")
        self.assertContains(response, "avatar-blank")

    def test_guest_cannot_view_profile_and_inactive_account_is_hidden(self):
        url = reverse("accounts:member_profile", args=(self.member.pk,))
        self.assertEqual(self.client.get(url).status_code, 302)

        self.member.is_active = False
        self.member.save(update_fields=["is_active"])
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_read_only_profile_accepts_only_get_requests(self):
        self.client.force_login(self.viewer)

        response = self.client.post(
            reverse("accounts:member_profile", args=(self.member.pk,)),
            {"bio": "Try to change this."},
        )

        self.assertEqual(response.status_code, 405)
        self.member.profile.refresh_from_db()
        self.assertEqual(self.member.profile.bio, "Builds small robots.")
