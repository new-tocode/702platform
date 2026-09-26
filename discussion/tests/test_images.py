"""帖子配图：张数、大小与文件校验。"""

import shutil
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils.datastructures import MultiValueDict
from ..forms import BoardForm, CommentForm, PostForm
from ..models import Board, Comment, Post, PostImage
from ..services import (
    BoardNameTaken,
    BoardNotEmpty,
    create_board,
    create_comment,
    create_post,
    delete_board,
    delete_comment,
    delete_post,
    DiscussionError,
    set_post_pinned,
    update_post,
)
from .factories import TEST_MEDIA_ROOT, TEST_PRIVATE_MEDIA_ROOT, png_upload


User = get_user_model()


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, PRIVATE_MEDIA_ROOT=TEST_PRIVATE_MEDIA_ROOT)
class DiscussionImageTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)
        shutil.rmtree(TEST_PRIVATE_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.member = User.objects.create_user(
            username="discussion-image-member",
            password="Member-Password-123!",
        )
        self.member.must_change_password = False
        self.member.save(update_fields=["must_change_password"])
        self.board = Board.objects.create(
            name_zh="图片测试",
            name="Image Tests",
            created_by=self.member,
        )

    def test_post_accepts_three_valid_images_and_cleans_files_on_delete(self):
        uploads = [png_upload(f"image-{number}.png") for number in range(3)]

        post = create_post(
            board_id=self.board.pk,
            title="Image post",
            content="Three images.",
            actor=self.member,
            images=uploads,
        )

        images = list(post.images.all())
        self.assertEqual(len(images), 3)
        self.assertTrue(all(image.file_size > 0 for image in images))
        stored_names = [image.image.name for image in images]
        storage = images[0].image.storage
        self.assertTrue(all(storage.exists(name) for name in stored_names))
        # upload_to 是函数时 Django 原样采用返回值：日期目录得自己算，别落下 %Y。
        for stored_name in stored_names:
            with self.subTest(stored_name=stored_name):
                self.assertNotIn("%", stored_name)
                self.assertRegex(
                    stored_name, r"^discussion/\d{4}/\d{2}/[0-9a-f]{32}\.png$"
                )

        delete_post(post_id=post.pk, actor=self.member)

        self.assertFalse(PostImage.objects.filter(post_id=post.pk).exists())
        self.assertTrue(all(not storage.exists(name) for name in stored_names))

    def test_fourth_image_and_images_over_three_megabytes_are_rejected(self):
        with self.assertRaises(DiscussionError):
            create_post(
                board_id=self.board.pk,
                title="Too many images",
                content="Four images.",
                actor=self.member,
                images=[png_upload(f"image-{number}.png") for number in range(4)],
            )

        oversized = SimpleUploadedFile(
            "large.png",
            b"x" * (3 * 1024 * 1024 + 1),
            content_type="image/png",
        )
        with self.assertRaises(DiscussionError):
            create_post(
                board_id=self.board.pk,
                title="Too large",
                content="Image exceeds the limit.",
                actor=self.member,
                images=[oversized],
            )

        corrupt = SimpleUploadedFile(
            "not-an-image.png",
            b"not a real image",
            content_type="image/png",
        )
        with self.assertRaises(DiscussionError):
            create_post(
                board_id=self.board.pk,
                title="Corrupt image",
                content="Image signature must be checked.",
                actor=self.member,
                images=[corrupt],
            )

        self.assertFalse(Post.objects.exists())

    def test_edit_can_remove_and_add_images_but_never_keep_more_than_three(self):
        post = create_post(
            board_id=self.board.pk,
            title="Editable images",
            content="Initial images.",
            actor=self.member,
            images=[png_upload("first.png"), png_upload("second.png")],
        )
        original_images = list(post.images.all())
        original_storage = original_images[0].image.storage
        removed_name = original_images[0].image.name

        update_post(
            post_id=post.pk,
            title=post.title,
            content=post.content,
            actor=self.member,
            remove_image_ids=[original_images[0].pk],
            images=[png_upload("replacement.png")],
        )

        self.assertEqual(post.images.count(), 2)
        self.assertFalse(original_storage.exists(removed_name))
        with self.assertRaises(DiscussionError):
            update_post(
                post_id=post.pk,
                title=post.title,
                content=post.content,
                actor=self.member,
                images=[png_upload("fourth.png"), png_upload("fifth.png")],
            )
        self.assertEqual(post.images.count(), 2)
        delete_post(post_id=post.pk, actor=self.member)

    def test_post_form_accepts_multiple_images_and_enforces_the_limit(self):
        form = PostForm(
            data={"title": "A title", "content": "A body"},
            files=MultiValueDict({"images": [png_upload(f"form-{n}.png") for n in range(3)]}),
        )
        self.assertTrue(form.is_valid(), form.errors)

        too_many = PostForm(
            data={"title": "A title", "content": "A body"},
            files=MultiValueDict({"images": [png_upload(f"form-{n}.png") for n in range(4)]}),
        )
        self.assertFalse(too_many.is_valid())
        self.assertIn("images", too_many.errors)
