"""Stage 1 acceptance tests for accounts and forced password changes."""

from io import BytesIO
import os
from pathlib import Path
import re
import shutil
import tempfile

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from core.models import AuditLog
from projects.models import ProjectGroup

from .forms import AdminUserChangeForm, AdminUserCreationForm, ProfileForm
from .models import GalleryImage
from .roles import describe_member
from .services import set_qualification


User = get_user_model()
TEST_MEDIA_ROOT = Path(tempfile.mkdtemp(prefix="competition-club-accounts-"))


def png_upload(name="avatar.png", size=(8, 8)):
    stream = BytesIO()
    Image.new("RGB", size, color="#12508f").save(stream, format="PNG")
    return SimpleUploadedFile(name, stream.getvalue(), content_type="image/png")


def oversized_png_upload(name="huge.png", megabytes=3):
    """一张真图、真超限：随机噪点压不动，尺寸按需要的 MB 数放大。"""
    pixels_per_side = int((megabytes * 1024 * 1024 / 3) ** 0.5) + 100
    stream = BytesIO()
    raw = os.urandom(pixels_per_side * pixels_per_side * 3)
    Image.frombytes("RGB", (pixels_per_side, pixels_per_side), raw).save(
        stream, format="PNG"
    )
    return SimpleUploadedFile(name, stream.getvalue(), content_type="image/png")


class AccountModelAcceptanceTests(TestCase):
    def test_member_accounts_require_first_password_change_and_get_profile(self):
        user = User.objects.create_user(
            username="member-001",
            password="Initial-Password-123!",
        )

        user.refresh_from_db()
        self.assertTrue(user.must_change_password)
        self.assertTrue(hasattr(user, "profile"))
        self.assertEqual(user.profile.user_id, user.pk)

    def test_superuser_created_by_manager_is_not_forced_to_change_password(self):
        user = User.objects.create_superuser(
            username="admin-001",
            password="Admin-Password-123!",
        )

        self.assertFalse(user.must_change_password)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)

    def test_name_is_one_field_in_member_and_admin_forms(self):
        member_fields = ProfileForm().fields
        creation_fields = AdminUserCreationForm().fields
        change_fields = AdminUserChangeForm(instance=User(username="form-user")).fields

        self.assertIn("full_name", member_fields)
        self.assertIn("full_name", creation_fields)
        self.assertIn("full_name", change_fields)
        self.assertNotIn("first_name", creation_fields)
        self.assertNotIn("last_name", creation_fields)
        self.assertNotIn("first_name", change_fields)
        self.assertNotIn("last_name", change_fields)


class MemberAuthenticationAcceptanceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="member-001",
            password="Initial-Password-123!",
            email="member@example.com",
        )

    def login_with_initial_password(self):
        return self.client.post(
            reverse("accounts:login"),
            {
                "username": self.user.username,
                "password": "Initial-Password-123!",
            },
        )

    def complete_first_password_change(self):
        self.login_with_initial_password()
        return self.client.post(
            reverse("accounts:password_change"),
            {
                "new_password1": "New-Password-456!",
                "new_password2": "New-Password-456!",
            },
        )

    def test_home_is_public_and_no_registration_route_exists(self):
        response = self.client.get(reverse("accounts:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "不开放公开注册")
        self.assertEqual(self.client.get("/register/").status_code, 404)

    def test_initial_login_redirects_directly_to_password_change(self):
        response = self.login_with_initial_password()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("accounts:password_change"))
        self.assertTrue(response.cookies)

    def test_forced_user_cannot_visit_member_features_before_password_change(self):
        self.login_with_initial_password()

        response = self.client.get(reverse("accounts:member_home"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:password_change"), response["Location"])
        self.assertIn("next=%2Fmember%2F", response["Location"])

    def test_first_password_change_unlocks_member_area_and_updates_flag(self):
        response = self.complete_first_password_change()

        self.user.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("accounts:member_home"))
        self.assertFalse(self.user.must_change_password)
        self.assertTrue(self.user.check_password("New-Password-456!"))
        self.assertEqual(self.client.get(reverse("accounts:member_home")).status_code, 200)

    def test_password_change_writes_safe_audit_event(self):
        self.complete_first_password_change()

        audit = AuditLog.objects.get(action="accounts.password.change")
        self.assertEqual(audit.user, self.user)
        self.assertEqual(audit.target_id, str(self.user.pk))
        self.assertEqual(audit.detail, {"forced_flow": True})
        self.assertNotIn("New-Password-456!", str(audit.detail))

    def test_forced_user_can_only_use_password_change_and_logout(self):
        self.login_with_initial_password()

        profile_response = self.client.get(reverse("accounts:profile"))
        password_response = self.client.get(reverse("accounts:password_change"))

        self.assertEqual(profile_response.status_code, 302)
        self.assertEqual(password_response.status_code, 200)
        self.assertContains(password_response, "请先修改初始密码")

    def test_member_can_update_profile_after_unlocking(self):
        self.complete_first_password_change()

        response = self.client.post(
            reverse("accounts:profile"),
            {
                "student_id": "20260001",
                "full_name": "成员一",
                "college": "计算机学院",
                "major": "软件工程",
                "specialty": "算法设计、机器人调试",
                "phone": "13800000000",
                "contact": "竞赛社团成员",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.full_name, "成员一")
        self.assertEqual(self.user.profile.student_id, "20260001")
        self.assertEqual(self.user.profile.college, "计算机学院")
        self.assertEqual(self.user.profile.specialty, "算法设计、机器人调试")

    def test_later_password_change_requires_old_password(self):
        self.complete_first_password_change()

        bad_response = self.client.post(
            reverse("accounts:password_change"),
            {
                "old_password": "wrong-password",
                "new_password1": "Another-Password-789!",
                "new_password2": "Another-Password-789!",
            },
        )
        self.assertEqual(bad_response.status_code, 200)
        self.assertContains(bad_response, "当前密码不正确")

        good_response = self.client.post(
            reverse("accounts:password_change"),
            {
                "old_password": "New-Password-456!",
                "new_password1": "Another-Password-789!",
                "new_password2": "Another-Password-789!",
            },
        )
        self.assertEqual(good_response.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Another-Password-789!"))
        self.assertFalse(self.user.must_change_password)

    def test_password_change_rejects_external_redirect(self):
        self.login_with_initial_password()

        response = self.client.post(
            f"{reverse('accounts:password_change')}?next=https://evil.example/",
            {
                "new_password1": "New-Password-456!",
                "new_password2": "New-Password-456!",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("accounts:member_home"))

    def test_failed_login_log_does_not_contain_password(self):
        with self.assertLogs("accounts", level="WARNING") as captured:
            response = self.client.post(
                reverse("accounts:login"),
                {
                    "username": self.user.username,
                    "password": "never-log-this-password",
                },
            )

        self.assertEqual(response.status_code, 200)
        combined_logs = "\n".join(captured.output)
        self.assertIn("auth.login.failure", combined_logs)
        self.assertNotIn("never-log-this-password", combined_logs)


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


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class AvatarAcceptanceTests(TestCase):
    """头像：上传、更换、删除，各自连文件一起处理；圆形只是显示层的裁切。"""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.user = User.objects.create_user(
            username="avatar-member",
            password="Member-Password-123!",
        )
        self.user.must_change_password = False
        self.user.save(update_fields=["must_change_password"])
        self.client.force_login(self.user)

    def upload(self, uploaded_file):
        return self.client.post(
            reverse("accounts:avatar_update"), {"avatar": uploaded_file}
        )

    def avatar_path(self):
        self.user.profile.refresh_from_db()
        return Path(self.user.profile.avatar.path)

    def test_uploading_an_avatar_stores_the_file_and_leaves_an_audit_row(self):
        response = self.upload(png_upload())

        self.assertRedirects(response, reverse("accounts:profile"))
        self.assertTrue(self.avatar_path().exists())
        self.user.profile.refresh_from_db()
        self.assertTrue(self.user.profile.avatar.name.startswith("avatars/"))
        self.assertTrue(
            AuditLog.objects.filter(action="accounts.avatar.update").exists()
        )

    def test_replacing_an_avatar_deletes_the_previous_file(self):
        self.upload(png_upload("first.png"))
        first = self.avatar_path()
        self.assertTrue(first.exists())

        self.upload(png_upload("second.png"))

        self.assertFalse(first.exists(), "旧头像文件应随更换删掉，不该留在磁盘上")
        self.assertTrue(self.avatar_path().exists())

    def test_deleting_an_avatar_clears_the_field_and_the_file(self):
        self.upload(png_upload())
        path = self.avatar_path()

        response = self.client.post(reverse("accounts:avatar_delete"))

        self.assertRedirects(response, reverse("accounts:profile"))
        self.user.profile.refresh_from_db()
        self.assertFalse(self.user.profile.avatar)
        self.assertFalse(path.exists())
        self.assertTrue(
            AuditLog.objects.filter(action="accounts.avatar.clear").exists()
        )

    def test_deleting_without_an_avatar_changes_nothing(self):
        response = self.client.post(reverse("accounts:avatar_delete"), follow=True)

        self.assertContains(response, "当前没有头像")
        self.assertFalse(
            AuditLog.objects.filter(action="accounts.avatar.clear").exists()
        )

    def test_avatar_larger_than_two_megabytes_is_rejected(self):
        # 跟着跳回个人信息页：提示语在那里，跳转不跟着走就被吃掉了。
        response = self.client.post(
            reverse("accounts:avatar_update"),
            {"avatar": oversized_png_upload()},
            follow=True,
        )

        self.assertContains(response, "不能超过 2 MB")
        self.user.profile.refresh_from_db()
        self.assertFalse(self.user.profile.avatar)

    def test_a_file_that_is_not_an_image_is_rejected(self):
        not_an_image = SimpleUploadedFile(
            "notes.png",
            b"just some text",
            content_type="image/png",
        )

        self.upload(not_an_image)

        self.user.profile.refresh_from_db()
        self.assertFalse(self.user.profile.avatar)

    def test_upload_requires_a_post_and_a_login(self):
        self.client.logout()
        self.assertEqual(
            self.upload(png_upload()).status_code,
            302,
        )

        self.client.force_login(self.user)
        self.assertEqual(
            self.client.get(reverse("accounts:avatar_update")).status_code,
            405,
        )

    def test_profile_page_shows_the_circle_and_the_three_actions(self):
        response = self.client.get(reverse("accounts:profile"))
        self.assertContains(response, 'class="avatar avatar-blank"')
        self.assertContains(response, "上传头像")
        self.assertNotContains(response, "删除头像")

        self.upload(png_upload("shown.png"))

        response = self.client.get(reverse("accounts:profile"))
        self.assertContains(response, 'class="avatar"')
        self.assertContains(response, "更换头像")
        self.assertContains(response, "删除头像")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class PersonalGalleryAcceptanceTests(TestCase):
    """个人图册：上传、排序、排布、删除，以及「单张 5 MB、合计 100 MB」两条上限。"""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.user = User.objects.create_user(
            username="gallery-member",
            password="Member-Password-123!",
        )
        self.user.must_change_password = False
        self.user.save(update_fields=["must_change_password"])
        self.client.force_login(self.user)

    def upload(self, name="photo.png", follow=False):
        return self.client.post(
            reverse("accounts:gallery_upload"),
            {"image": png_upload(name)},
            follow=follow,
        )

    def images(self):
        return list(self.user.profile.gallery_images.all())

    def test_uploading_an_image_stores_it_at_the_end_of_the_gallery(self):
        self.upload("first.png")
        self.upload("second.png")

        images = self.images()
        self.assertEqual(len(images), 2)
        self.assertEqual(images[0].image.name.startswith("gallery/"), True)
        self.assertLess(images[0].sort_order, images[1].sort_order)
        self.assertGreater(images[0].file_size, 0)
        self.assertTrue(AuditLog.objects.filter(action="accounts.gallery.add").exists())

    def test_an_image_larger_than_five_megabytes_is_rejected(self):
        response = self.client.post(
            reverse("accounts:gallery_upload"),
            {"image": oversized_png_upload(name="big.png", megabytes=6)},
            follow=True,
        )

        self.assertContains(response, "不能超过 5 MB")
        self.assertEqual(self.images(), [])

    def test_the_gallery_total_cap_is_enforced_on_upload(self):
        kept = GalleryImage.objects.create(
            profile=self.user.profile, image=png_upload("kept.png")
        )
        # 直接把已用量抬到 99 MB，不必真造一张那么大的图。
        GalleryImage.objects.filter(pk=kept.pk).update(
            file_size=99 * 1024 * 1024
        )
        oversized = oversized_png_upload(name="filler.png", megabytes=3)

        response = self.client.post(
            reverse("accounts:gallery_upload"), {"image": oversized}, follow=True
        )

        self.assertContains(response, "图册合计不能超过 100 MB")
        self.assertEqual(len(self.images()), 1)
        self.assertTrue(
            Path(kept.image.path).exists(), "被拒的上传不该动到已有图像"
        )

    def test_moving_an_image_swaps_it_with_its_neighbour(self):
        self.upload("first.png")
        self.upload("second.png")
        first, second = self.images()

        self.client.post(
            reverse("accounts:gallery_image_move", args=[second.pk]),
            {"direction": "up"},
        )

        self.assertEqual([image.pk for image in self.images()], [second.pk, first.pk])
        self.assertEqual([image.sort_order for image in self.images()], [0, 1])
        self.assertTrue(
            AuditLog.objects.filter(action="accounts.gallery.reorder").exists()
        )

    def test_moving_past_either_end_keeps_the_order_and_says_so(self):
        self.upload("only.png")
        only = self.images()[0]

        up = self.client.post(
            reverse("accounts:gallery_image_move", args=[only.pk]),
            {"direction": "up"},
            follow=True,
        )
        down = self.client.post(
            reverse("accounts:gallery_image_move", args=[only.pk]),
            {"direction": "down"},
            follow=True,
        )

        self.assertContains(up, "已经是第一张了")
        self.assertContains(down, "已经是最后一张了")
        self.assertEqual([image.pk for image in self.images()], [only.pk])

    def test_layout_can_be_changed_and_is_rendered_on_the_page(self):
        self.upload("wide.png")
        image = self.images()[0]

        self.client.post(
            reverse("accounts:gallery_image_layout", args=[image.pk]),
            {"layout": "wide"},
        )

        image.refresh_from_db()
        self.assertEqual(image.layout, "wide")
        response = self.client.get(reverse("accounts:profile"))
        self.assertContains(response, 'class="gitem gitem-wide"')

    def test_changing_the_layout_does_not_re_read_the_image(self):
        """换排布只写那一列：图片文件即使不在磁盘上，也不该挡着改排布。"""
        self.upload("moved.png")
        image = self.images()[0]
        Path(image.image.path).unlink()

        response = self.client.post(
            reverse("accounts:gallery_image_layout", args=[image.pk]),
            {"layout": "full"},
        )

        self.assertRedirects(response, reverse("accounts:profile"))
        image.refresh_from_db()
        self.assertEqual(image.layout, "full")

    def test_deleting_an_image_removes_the_row_and_the_file(self):
        self.upload("doomed.png")
        image = self.images()[0]
        path = Path(image.image.path)

        response = self.client.post(
            reverse("accounts:gallery_image_delete", args=[image.pk])
        )

        self.assertRedirects(response, reverse("accounts:profile"))
        self.assertEqual(self.images(), [])
        self.assertFalse(path.exists())
        self.assertTrue(
            AuditLog.objects.filter(action="accounts.gallery.delete").exists()
        )

    def test_another_members_image_is_out_of_reach(self):
        owner = User.objects.create_user(
            username="gallery-owner",
            password="Owner-Password-123!",
        )
        foreign = GalleryImage.objects.create(
            profile=owner.profile, image=png_upload("foreign.png")
        )

        for name, payload in (
            ("accounts:gallery_image_move", {"direction": "up"}),
            ("accounts:gallery_image_layout", {"layout": "full"}),
            ("accounts:gallery_image_delete", {}),
        ):
            with self.subTest(view=name):
                response = self.client.post(reverse(name, args=[foreign.pk]), payload)
                self.assertEqual(response.status_code, 404)

        foreign.refresh_from_db()
        self.assertEqual(foreign.layout, "normal")
        self.assertTrue(Path(foreign.image.path).exists())

    def test_unknown_direction_or_layout_is_a_404(self):
        self.upload("steady.png")
        image = self.images()[0]

        moved = self.client.post(
            reverse("accounts:gallery_image_move", args=[image.pk]),
            {"direction": "sideways"},
        )
        laid_out = self.client.post(
            reverse("accounts:gallery_image_layout", args=[image.pk]),
            {"layout": "enormous"},
        )

        self.assertEqual(moved.status_code, 404)
        self.assertEqual(laid_out.status_code, 404)

    def test_gallery_actions_require_a_login_and_a_post(self):
        self.upload("mine.png")
        image = self.images()[0]

        self.assertEqual(
            self.client.get(reverse("accounts:gallery_upload")).status_code, 405
        )
        self.assertEqual(
            self.client.get(reverse("accounts:gallery_image_delete", args=[image.pk])).status_code,
            405,
        )

        self.client.logout()
        self.assertEqual(self.upload("anonymous.png").status_code, 302)

    def test_the_page_shows_the_upload_row_usage_and_each_image(self):
        response = self.client.get(reverse("accounts:profile"))
        self.assertContains(response, "图册还是空的")

        self.upload("shown.png")

        response = self.client.get(reverse("accounts:profile"))
        self.assertContains(response, "个人图册")
        self.assertContains(response, "每张不超过 5 MB，图册合计不超过 100 MB")
        self.assertContains(response, "1 张 · 0 / 100 MB")
        self.assertContains(response, 'class="gitem gitem-normal"')
        self.assertContains(response, "加入图册")


class ProfileIdentityPanelAcceptanceTests(TestCase):
    """个人信息页右栏的「当前身份」：只列实际持有的，对象身份带组名。"""

    def setUp(self):
        self.member = User.objects.create_user(
            username="identity-member",
            password="Member-Password-123!",
        )
        self.member.must_change_password = False
        self.member.save(update_fields=["must_change_password"])
        self.client.force_login(self.member)

    def identities_on_page(self):
        """页面上这一栏画出来的身份标签与组名，各按出现顺序。

        整页只有这一处会画身份标签（``.chip-on``）与组名（``.member``），
        所以不用先切出面板那一段。
        """
        html = self.client.get(reverse("accounts:profile")).content.decode()
        return (
            re.findall(r'<span class="chip chip-on">(.*?)</span>', html),
            re.findall(r'<span class="member">(.*?)</span>', html),
        )

    def test_a_member_without_extra_identities_sees_an_empty_note(self):
        response = self.client.get(reverse("accounts:profile"))
        labels, groups = self.identities_on_page()

        self.assertEqual(labels, [])
        self.assertEqual(groups, [])
        self.assertContains(response, "暂无其他身份")

    def test_every_held_identity_is_listed_in_catalog_order(self):
        self.member.is_staff = True
        self.member.is_reviewer = True
        self.member.is_super_reviewer = True
        self.member.save(
            update_fields=["is_staff", "is_reviewer", "is_super_reviewer"]
        )

        labels, _groups = self.identities_on_page()

        self.assertEqual(labels, ["管理员", "评审人", "超级评审"])

    def test_qualifications_left_off_are_not_listed(self):
        self.member.is_preliminary_reviewer = True
        self.member.save(update_fields=["is_preliminary_reviewer"])

        labels, _groups = self.identities_on_page()

        self.assertEqual(labels, ["初审人"])

    def test_object_identities_carry_their_group_names(self):
        ProjectGroup.objects.create(name="星火计划组", leader=self.member)
        joined = ProjectGroup.objects.create(
            name="星河计划组",
            leader=User.objects.create_user(
                username="identity-leader",
                password="Leader-Password-123!",
            ),
        )
        joined.members.add(self.member)

        labels, groups = self.identities_on_page()

        self.assertEqual(labels, ["项目组联系人", "项目组成员"])
        self.assertIn("星火计划组", groups)
        self.assertIn("星河计划组", groups)

    def test_a_group_member_is_listed_without_being_a_contact(self):
        joined = ProjectGroup.objects.create(
            name="只有成员组",
            leader=User.objects.create_user(
                username="identity-leader",
                password="Leader-Password-123!",
            ),
        )
        joined.members.add(self.member)

        labels, groups = self.identities_on_page()

        self.assertEqual(labels, ["项目组成员"])
        self.assertEqual(groups, ["只有成员组"])

    def test_the_panel_is_read_only_and_sits_below_the_avatar(self):
        self.member.is_reviewer = True
        self.member.save(update_fields=["is_reviewer"])

        response = self.client.get(reverse("accounts:profile"))

        self.assertContains(response, "只读")
        html = response.content.decode()
        self.assertLess(html.index("头像"), html.index("当前身份"))


class MemberRoleDisplayAcceptanceTests(TestCase):
    """成员中心显示当前身份；口径见 accounts/roles.py。"""

    def setUp(self):
        self.member = User.objects.create_user(
            username="role-member",
            password="Member-Password-123!",
        )
        self.contact = User.objects.create_user(
            username="role-contact",
            password="Contact-Password-123!",
        )
        self.staff = User.objects.create_user(
            username="role-staff",
            password="Staff-Password-123!",
        )
        self.staff.is_staff = True
        for user in (self.member, self.contact, self.staff):
            user.must_change_password = False
            user.save(update_fields=["must_change_password", "is_staff"])
        self.group = ProjectGroup.objects.create(name="角色测试组", leader=self.contact)

    def assert_role_cell(self, response, role):
        # 页脚也有「管理员」等字样，因此断言精确到身份单元格本身。
        self.assertContains(response, f'<div class="v text">{role}</div>')

    def test_anonymous_is_described_as_guest(self):
        self.assertEqual(describe_member(AnonymousUser()), "游客")

    def test_member_without_group_is_described_as_no_group(self):
        self.client.force_login(self.member)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertContains(response, "当前身份")
        self.assert_role_cell(response, "未加入项目组")

    def test_group_member_is_described_as_group_member(self):
        self.group.members.add(self.member)
        self.client.force_login(self.member)

        response = self.client.get(reverse("accounts:member_home"))

        self.assert_role_cell(response, "项目组成员")

    def test_contact_is_described_as_project_contact(self):
        self.client.force_login(self.contact)

        response = self.client.get(reverse("accounts:member_home"))

        self.assert_role_cell(response, "项目组联系人")

    def test_staff_is_described_as_admin(self):
        self.client.force_login(self.staff)

        response = self.client.get(reverse("accounts:member_home"))

        self.assert_role_cell(response, "管理员")

    def test_platform_overview_is_visible_to_admin_and_contact_only(self):
        for user, sees_overview in (
            (self.staff, True),
            (self.contact, True),
            (self.member, False),
        ):
            with self.subTest(username=user.username):
                self.client.force_login(user)

                response = self.client.get(reverse("accounts:member_home"))

                if sees_overview:
                    self.assertContains(response, "社团概览")
                    self.assertContains(response, "在册成员")
                else:
                    self.assertNotContains(response, "社团概览")
                    self.assertNotContains(response, "在册成员")

    def test_public_home_no_longer_exposes_platform_overview(self):
        response = self.client.get(reverse("accounts:home"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "在册成员")
        self.assertNotContains(response, "在借设备")

    def test_member_home_drops_permission_hint_and_entry_counter_box(self):
        self.client.force_login(self.member)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertNotContains(response, "可用入口按当前账号权限显示")
        self.assertNotContains(response, '<div class="k">可用入口</div>')


class AdminProvisioningAcceptanceTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin-001",
            password="Admin-Password-123!",
        )
        self.client.force_login(self.admin)

    def test_admin_can_create_member_with_forced_change_flag(self):
        response = self.client.post(
            reverse("admin:accounts_user_add"),
            {
                "username": "member-002",
                "email": "member2@example.com",
                "full_name": "成员二",
                "password1": "Initial-Password-234!",
                "password2": "Initial-Password-234!",
                "_save": "保存",
            },
        )

        self.assertIn(response.status_code, {200, 302})
        member = User.objects.get(username="member-002")
        self.assertTrue(member.must_change_password)
        self.assertEqual(member.profile.full_name, "成员二")
        self.assertTrue(member.check_password("Initial-Password-234!"))

    def test_admin_user_editor_exposes_one_name_field(self):
        member = User.objects.create_user(
            username="member-name-editor",
            password="Initial-Password-678!",
        )
        member.profile.full_name = "已有姓名"
        member.profile.save(update_fields=["full_name"])

        response = self.client.get(
            reverse("admin:accounts_user_change", args=(member.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="full_name"')
        self.assertContains(response, "已有姓名")
        self.assertNotContains(response, 'name="first_name"')
        self.assertNotContains(response, 'name="last_name"')

    def test_admin_password_reset_restarts_forced_change_cycle(self):
        member = User.objects.create_user(
            username="member-003",
            password="Old-Password-345!",
        )
        member.must_change_password = False
        member.save(update_fields=["must_change_password"])

        response = self.client.post(
            reverse("admin:auth_user_password_change", args=(member.pk,)),
            {
                "password1": "Reset-Password-567!",
                "password2": "Reset-Password-567!",
                "usable_password": "true",
                "_save": "保存",
            },
        )

        self.assertEqual(response.status_code, 302)
        member.refresh_from_db()
        self.assertTrue(member.must_change_password)
        self.assertTrue(member.check_password("Reset-Password-567!"))

    def test_admin_can_open_user_list_but_member_cannot_use_admin(self):
        response = self.client.get(reverse("admin:accounts_user_changelist"))
        self.assertEqual(response.status_code, 200)

        member = User.objects.create_user(
            username="member-004",
            password="Initial-Password-456!",
        )
        self.client.force_login(member)
        member_admin_response = self.client.get("/admin/")
        self.assertEqual(member_admin_response.status_code, 302)

    def test_admin_group_pages_load_and_list_group_members(self):
        member = User.objects.create_user(
            username="member-in-group",
            password="Initial-Password-789!",
        )
        member.profile.full_name = "组内成员"
        member.profile.save(update_fields=["full_name"])
        group = Group.objects.create(name="测试用户组")
        member.groups.add(group)

        list_response = self.client.get(reverse("admin:auth_group_changelist"))
        change_response = self.client.get(
            reverse("admin:auth_group_change", args=(group.pk,))
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, "测试用户组")
        self.assertEqual(change_response.status_code, 200)
        self.assertContains(change_response, "组内成员")


class RoleRosterAcceptanceTests(TestCase):
    """身份名册与批量授予——后台唯一能直接发放身份的地方。

    名册本身只读。全局身份的授予与撤销走用户列表页的批量动作；对象身份
    （项目组联系人、成员）连批量动作都没有，只能由业务动作产生。
    """

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin-roles",
            password="Admin-Password-123!",
        )
        self.client.force_login(self.admin)

    def _member(self, username, full_name):
        user = User.objects.create_user(
            username=username,
            password="Initial-Password-123!",
        )
        user.profile.full_name = full_name
        user.profile.save(update_fields=["full_name"])
        return user

    def test_roster_lists_exactly_the_holders(self):
        holder = self._member("roster-holder", "有名册的人")
        holder.is_reviewer = True
        holder.save(update_fields=["is_reviewer"])
        self._member("roster-outsider", "不在名册的人")

        response = self.client.get(reverse("admin:accounts_reviewerrole_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "有名册的人")
        self.assertNotContains(response, "不在名册的人")

    def test_roster_shows_every_identity_a_person_holds(self):
        holder = self._member("roster-multi", "多重身份")
        holder.is_reviewer = True
        holder.is_super_reviewer = True
        holder.save(update_fields=["is_reviewer", "is_super_reviewer"])

        response = self.client.get(reverse("admin:accounts_reviewerrole_changelist"))

        self.assertContains(response, "评审人、超级评审")

    def test_all_six_rosters_load(self):
        for name in (
            "admin:accounts_adminrole_changelist",
            "admin:accounts_reviewerrole_changelist",
            "admin:accounts_preliminaryreviewerrole_changelist",
            "admin:accounts_superreviewerrole_changelist",
            "admin:projects_projectcontact_changelist",
            "admin:projects_projectmember_changelist",
        ):
            with self.subTest(roster=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_rosters_offer_no_way_to_hand_out_an_identity(self):
        """名册能看不能发——发资格在用户列表页，对象身份则只能由业务动作产生。"""
        for name in (
            "admin:accounts_reviewerrole_add",
            "admin:projects_projectcontact_add",
            "admin:projects_projectmember_add",
        ):
            with self.subTest(add_page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 403)

    def test_bulk_action_grants_then_revokes_reviewer_qualification(self):
        first = self._member("bulk-one", "甲")
        second = self._member("bulk-two", "乙")
        selected = [str(first.pk), str(second.pk)]
        listing = reverse("admin:accounts_user_changelist")

        self.client.post(
            listing,
            {"action": "grant_is_reviewer", "_selected_action": selected, "index": "0"},
            follow=True,
        )
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertTrue(first.is_reviewer)
        self.assertTrue(second.is_reviewer)
        self.assertTrue(
            AuditLog.objects.filter(action="accounts.qualification.grant").exists()
        )

        self.client.post(
            listing,
            {"action": "revoke_is_reviewer", "_selected_action": selected, "index": "0"},
            follow=True,
        )
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_reviewer)
        self.assertFalse(second.is_reviewer)

    def test_granting_someone_who_already_has_it_leaves_no_audit_row(self):
        member = self._member("bulk-idempotent", "丙")
        member.is_reviewer = True
        member.save(update_fields=["is_reviewer"])

        self.client.post(
            reverse("admin:accounts_user_changelist"),
            {
                "action": "grant_is_reviewer",
                "_selected_action": [str(member.pk)],
                "index": "0",
            },
            follow=True,
        )

        member.refresh_from_db()
        self.assertTrue(member.is_reviewer)
        # 取值没变就不算一次授予，也就没有新的审计行。
        self.assertFalse(
            AuditLog.objects.filter(action="accounts.qualification.grant").exists()
        )

    def test_no_bulk_action_hands_out_admin_access(self):
        """把一批人放进后台该是逐个确认的事，不该由一次批量动作完成。"""
        response = self.client.get(reverse("admin:accounts_user_changelist"))

        self.assertNotContains(response, "授予管理员资格")
        self.assertNotContains(response, "撤销管理员资格")

    def test_service_refuses_flags_outside_the_allowlist(self):
        with self.assertRaises(ValueError):
            set_qualification(
                users=[self.admin],
                flag="is_superuser",
                value=True,
                actor=self.admin,
            )

    def test_new_account_can_be_given_qualifications_right_away(self):
        response = self.client.post(
            reverse("admin:accounts_user_add"),
            {
                "username": "member-with-roles",
                "email": "roles@example.com",
                "full_name": "带资格的新人",
                "password1": "Initial-Password-234!",
                "password2": "Initial-Password-234!",
                "is_reviewer": "on",
                "is_preliminary_reviewer": "on",
                "_save": "保存",
            },
        )

        self.assertIn(response.status_code, {200, 302})
        member = User.objects.get(username="member-with-roles")
        self.assertTrue(member.is_reviewer)
        self.assertTrue(member.is_preliminary_reviewer)
        self.assertFalse(member.is_super_reviewer)
