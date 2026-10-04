"""个人图册：批量上传、排序、排布、删除，以及「单张 5 MB、合计 100 MB」两条上限。"""

import hashlib
import shutil
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import AuditLog

from ..models import GALLERY_TOTAL_MAX_BYTES, GalleryImage
from .factories import (
    TEST_MEDIA_ROOT,
    TEST_PRIVATE_MEDIA_ROOT,
    oversized_png_upload,
    png_upload,
)


User = get_user_model()


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, PRIVATE_MEDIA_ROOT=TEST_PRIVATE_MEDIA_ROOT)
class PersonalGalleryAcceptanceTests(TestCase):
    """个人图册：批量上传、排序、排布、删除，以及「单张 5 MB、合计 100 MB」两条上限。

    批量上传的语义是「能放下的先放」：一批里格式不合格或放不下的逐张跳过并点名，
    其余照常入册——所以下面几处断言的是「进了几张、谁被点名」，不是整批的成败。
    """

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
        return self.upload_batch([png_upload(name)], follow=follow)

    def upload_batch(self, files, follow=False):
        return self.client.post(
            reverse("accounts:gallery_upload"),
            {"images": files},
            follow=follow,
        )

    def images(self):
        return list(self.user.profile.gallery_images.all())

    def stored_files(self):
        """受保护目录里图册落盘的文件名，用于确认被拒的上传没有留下文件。"""
        root = TEST_PRIVATE_MEDIA_ROOT / "gallery"
        if not root.exists():
            return []
        return sorted(path.name for path in root.rglob("*") if path.is_file())

    @staticmethod
    def digest(upload):
        payload = upload.read()
        upload.seek(0)
        return hashlib.sha256(payload).hexdigest()

    def test_uploading_an_image_stores_it_at_the_end_of_the_gallery(self):
        self.upload("first.png")
        self.upload("second.png")

        images = self.images()
        self.assertEqual(len(images), 2)
        self.assertEqual(images[0].image.name.startswith("gallery/"), True)
        self.assertLess(images[0].sort_order, images[1].sort_order)
        self.assertGreater(images[0].file_size, 0)
        self.assertTrue(AuditLog.objects.filter(action="accounts.gallery.add").exists())

    def test_uploading_an_image_records_its_sha256(self):
        upload = png_upload("hashed.png")
        expected = self.digest(upload)

        self.upload_batch([upload])

        self.assertEqual(self.images()[0].sha256, expected)

    def test_a_batch_is_added_in_the_chosen_order(self):
        """一次选三张：都进图册，顺序就是选择顺序，每张各记一条审计。"""
        uploads = [
            png_upload("one.png", size=(8, 8)),
            png_upload("two.png", size=(9, 9)),
            png_upload("three.png", size=(10, 10)),
        ]
        digests = [self.digest(upload) for upload in uploads]

        response = self.upload_batch(uploads, follow=True)

        self.assertContains(response, "3 张图像已加入图册。")
        images = self.images()
        self.assertEqual([image.sha256 for image in images], digests)
        orders = [image.sort_order for image in images]
        self.assertEqual(orders, sorted(orders), "sort_order 没有按选择顺序递增")
        self.assertEqual(
            AuditLog.objects.filter(action="accounts.gallery.add").count(), 3
        )

    def test_a_bad_file_is_named_and_the_rest_of_the_batch_still_lands(self):
        """一批里有不合格的：点名跳过它，合格的那几张照常入册。"""
        response = self.upload_batch(
            [
                png_upload("fine.png"),
                oversized_png_upload(name="heavy.png", megabytes=6),
                SimpleUploadedFile(
                    "notes.txt", b"not an image", content_type="text/plain"
                ),
            ],
            follow=True,
        )

        self.assertContains(response, "1 张图像已加入图册。")
        self.assertContains(response, "heavy.png：图册图像不能超过 5 MB。")
        self.assertContains(response, "notes.txt：图册图像仅支持")
        self.assertEqual(len(self.images()), 1)

    def test_the_batch_keeps_what_fits_and_names_what_does_not(self):
        """放不下的跳过、放得下的照加；跳过一张后仍会接着试后面的。"""
        kept = GalleryImage.objects.create(
            profile=self.user.profile, image=png_upload("kept.png")
        )
        # 已用量抬到「小图放得下、大图放不下」：离上限只差 2 MB，
        # 而下面两张真图的大小由各自的字节数决定（约 1 MB 与 3 MB）。
        GalleryImage.objects.filter(pk=kept.pk).update(
            file_size=GALLERY_TOTAL_MAX_BYTES - 2 * 1024 * 1024
        )

        response = self.upload_batch(
            [
                oversized_png_upload(name="fits.png", megabytes=1),
                oversized_png_upload(name="over.png", megabytes=3),
                png_upload("fits-too.png"),
            ],
            follow=True,
        )

        self.assertContains(response, "2 张图像已加入图册。")
        self.assertContains(response, "另有 1 张因图册容量不足未加入")
        self.assertContains(response, "over.png")
        # 三张 = 原有的 + fits + fits-too：跳过 over 之后仍试了第三张。
        self.assertEqual(len(self.images()), 3)
        self.assertNotContains(response, "fits-too.png：")
        self.assertTrue(
            Path(kept.image.path).exists(), "被拒的上传不该动到已有图像"
        )

    def test_a_batch_that_cannot_fit_at_all_adds_nothing(self):
        kept = GalleryImage.objects.create(
            profile=self.user.profile, image=png_upload("kept.png")
        )
        GalleryImage.objects.filter(pk=kept.pk).update(
            file_size=GALLERY_TOTAL_MAX_BYTES
        )

        response = self.upload_batch(
            [png_upload("first.png"), png_upload("second.png")], follow=True
        )

        self.assertContains(response, "另有 2 张因图册容量不足未加入")
        self.assertEqual(len(self.images()), 1)

    def test_uploading_without_picking_a_file_says_so(self):
        response = self.upload_batch([], follow=True)

        self.assertContains(response, "请选择要上传的图片。")
        self.assertEqual(self.images(), [])

    def test_a_failed_batch_rolls_back_and_cleans_up_the_stored_files(self):
        """保存中途出错：数据库回滚，已经落盘的那几张也要跟着删掉。"""
        before = self.stored_files()
        real_save = GalleryImage.save
        saved = []

        def failing_second_save(instance, *args, **kwargs):
            saved.append(instance)
            if len(saved) == 2:
                raise RuntimeError("磁盘满了")
            return real_save(instance, *args, **kwargs)

        with mock.patch.object(GalleryImage, "save", failing_second_save):
            with self.assertRaises(RuntimeError):
                self.upload_batch([png_upload("one.png"), png_upload("two.png")])

        self.assertEqual(self.images(), [])
        self.assertEqual(
            self.stored_files(), before, "回滚之后不该留下没人认领的文件"
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

    def test_the_file_input_lets_the_browser_pick_several_files(self):
        """多选就落在 ``multiple`` 这一个属性上，由 ``MultipleFileInput`` 渲染。"""
        response = self.client.get(reverse("accounts:profile"))

        self.assertRegex(
            response.content.decode(),
            r'<input[^>]*name="images"[^>]*multiple',
        )
        # 即时反馈那句话与上限都挂在页面里，供 gallery.js 取用。
        self.assertContains(response, "data-gallery-picked")
        self.assertContains(response, 'data-max-bytes="5242880"')
