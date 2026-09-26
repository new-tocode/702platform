"""个人图册：上传、排序、排布、删除，以及「单张 5 MB、合计 100 MB」两条上限。"""

import re
import shutil
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import AuditLog
from ..models import GalleryImage
from .factories import (
    TEST_MEDIA_ROOT,
    TEST_PRIVATE_MEDIA_ROOT,
    oversized_png_upload,
    png_upload,
)


User = get_user_model()


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, PRIVATE_MEDIA_ROOT=TEST_PRIVATE_MEDIA_ROOT)
@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, PRIVATE_MEDIA_ROOT=TEST_PRIVATE_MEDIA_ROOT)
class PersonalGalleryAcceptanceTests(TestCase):
    """个人图册：上传、排序、排布、删除，以及「单张 5 MB、合计 100 MB」两条上限。"""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)
        shutil.rmtree(TEST_PRIVATE_MEDIA_ROOT, ignore_errors=True)

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
