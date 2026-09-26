"""头像：上传、更换、删除，各自连文件一起处理；圆形只是显示层的裁切。"""

import re
import shutil
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import AuditLog
from .factories import (
    TEST_MEDIA_ROOT,
    TEST_PRIVATE_MEDIA_ROOT,
    oversized_png_upload,
    png_upload,
)


User = get_user_model()


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, PRIVATE_MEDIA_ROOT=TEST_PRIVATE_MEDIA_ROOT)
class AvatarAcceptanceTests(TestCase):
    """头像：上传、更换、删除，各自连文件一起处理；圆形只是显示层的裁切。"""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)
        shutil.rmtree(TEST_PRIVATE_MEDIA_ROOT, ignore_errors=True)

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
