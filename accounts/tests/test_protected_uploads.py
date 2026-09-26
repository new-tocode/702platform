"""受保护上传件：头像与图册落在私有目录，取文件一律经视图。"""

from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import AuditLog
from ..models import GalleryImage
from .factories import (
    TEST_MEDIA_ROOT,
    TEST_PRIVATE_MEDIA_ROOT,
    png_upload,
)


User = get_user_model()


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, PRIVATE_MEDIA_ROOT=TEST_PRIVATE_MEDIA_ROOT)
class ProtectedUploadAccessTests(TestCase):
    """头像与图册不在公开的 /media/ 下，只能经视图取，且要登录。

    这一条是「权限判定真的在把关」与「只是一句君子协定」的分界：过去这些文件
    躺在 Nginx 直出的 mediafiles/ 里，谁拿到路径谁就能取，视图里那些判定形同
    虚设。现在它们落在 PRIVATE_MEDIA_ROOT，而 /media/ 指不到那里。
    """

    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(
            username="protected-owner",
            password="Owner-Password-123!",
        )
        cls.owner.must_change_password = False
        cls.owner.save(update_fields=["must_change_password"])
        cls.other = User.objects.create_user(
            username="protected-other",
            password="Other-Password-123!",
        )
        cls.other.must_change_password = False
        cls.other.save(update_fields=["must_change_password"])

    def setUp(self):
        from ..models import Profile

        self.profile = Profile.objects.get(user=self.owner)
        self.profile.avatar.save("我的头像.png", png_upload(), save=True)
        # GalleryImage.save() 里跑 full_clean()，没有图建不出来——所以先建行再存图，
        # 与 add_gallery_image 服务层的顺序一致。
        self.image = GalleryImage(profile=self.profile)
        self.image.image.save("我的照片.png", png_upload(), save=True)

    def test_avatar_is_stored_outside_the_public_media_root(self):
        self.profile.refresh_from_db()

        self.assertTrue(
            Path(self.profile.avatar.path).is_relative_to(TEST_PRIVATE_MEDIA_ROOT),
            "头像没有落在受保护目录里",
        )
        self.assertFalse(
            Path(self.profile.avatar.path).is_relative_to(TEST_MEDIA_ROOT),
            "头像仍然落在公开的 media 目录下",
        )

    def test_stored_name_carries_no_user_information(self):
        """落盘名换成 uuid：原名会带人名，而文件名会跟着文件走进备份与运维的 ls。"""
        self.profile.refresh_from_db()

        stored = Path(self.profile.avatar.name).name
        self.assertNotIn("我的头像", stored)
        self.assertNotIn(self.owner.username, stored)
        self.assertTrue(stored.endswith(".png"))

    def test_protected_storage_hands_out_no_url(self):
        """受保护的存储给不出公开地址。

        这里刻意**不是**抛异常：Django 的 ClearableFileInput.is_initial() 会
        getattr(value, "url", False)，真去求值这个属性，抛异常会让 {{ form.x }}
        在模板最深处炸掉（实测 500）。所以口径是「返回空串」，而「必须走视图」
        由目录边界保证——受保护目录不在 MEDIA_ROOT 之下。
        """
        from core.storage import private_storage

        self.assertEqual(private_storage.url("avatars/2026/09/whatever.png"), "")

    def test_avatar_file_is_served_to_a_logged_in_member(self):
        self.client.force_login(self.other)

        response = self.client.get(
            reverse("accounts:avatar_file", args=(self.owner.pk,))
        )

        self.assertEqual(response.status_code, 200)

    def test_gallery_file_is_served_to_a_logged_in_member(self):
        self.client.force_login(self.other)

        response = self.client.get(
            reverse("accounts:gallery_file", args=(self.image.pk,))
        )

        self.assertEqual(response.status_code, 200)

    def test_anonymous_visitor_gets_no_avatar(self):
        response = self.client.get(
            reverse("accounts:avatar_file", args=(self.owner.pk,))
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def test_anonymous_visitor_gets_no_gallery_image(self):
        response = self.client.get(
            reverse("accounts:gallery_file", args=(self.image.pk,))
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def test_member_without_an_avatar_gets_404_not_500(self):
        member = User.objects.create_user(
            username="protected-no-avatar",
            password="No-Avatar-Password-123!",
        )
        member.must_change_password = False
        member.save(update_fields=["must_change_password"])
        self.client.force_login(member)

        response = self.client.get(reverse("accounts:avatar_file", args=(member.pk,)))

        self.assertEqual(response.status_code, 404)
