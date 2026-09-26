"""帖子：发布、编辑、配图、取图、删除、置顶取值。"""

from django.contrib.auth import get_user_model
from django.urls import reverse
from ..models import Board, Comment, Post, PostImage
from .base import DiscussionViewTestCase
from .factories import png_upload


class PostViewTests(DiscussionViewTestCase):
    def test_post_create_uses_logged_in_author_and_post_edit_is_owner_only(self):
        self.client.force_login(self.member)
        response = self.client.post(
            reverse("discussion:post_new", args=(self.board.pk,)),
            {
                "title": "New from form",
                "content": "Created by the logged-in author.",
                "author": self.other_member.pk,
            },
        )

        post = Post.objects.get(title="New from form")
        self.assertEqual(post.author, self.member)
        self.assertRedirects(
            response,
            reverse("discussion:board", args=(self.board.pk,)),
        )

        edit_response = self.client.post(
            reverse("discussion:post_edit", args=(post.pk,)),
            {"title": "Edited by author", "content": "Updated body."},
        )
        self.assertRedirects(
            edit_response,
            reverse("discussion:board", args=(self.board.pk,)),
        )
        post.refresh_from_db()
        self.assertEqual(post.title, "Edited by author")

        self.assertEqual(
            self.client.put(
                reverse("discussion:post_edit", args=(post.pk,)),
                {"title": "Not allowed", "content": "Wrong method."},
            ).status_code,
            405,
        )
        other_post = self._post(author=self.other_member)
        denied = self.client.get(
            reverse("discussion:post_edit", args=(other_post.pk,))
        )
        self.assertEqual(denied.status_code, 403)
    def test_http_post_uploads_images_and_edit_can_remove_one(self):
        self.client.force_login(self.member)
        response = self.client.post(
            reverse("discussion:post_new", args=(self.board.pk,)),
            {
                "title": "Post with photos",
                "content": "Photo body.",
                "images": [png_upload("first.png"), png_upload("second.png")],
            },
        )
        post = Post.objects.get(title="Post with photos")
        images = list(post.images.all())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(images), 2)
        self.assertTrue(
            self.client.get(reverse("discussion:board", args=(self.board.pk,)))
            .content.decode()
            .count("discussion-post-images")
            >= 1
        )
        first_image = images[0]
        storage = first_image.image.storage
        file_name = first_image.image.name

        edit_response = self.client.post(
            reverse("discussion:post_edit", args=(post.pk,)),
            {
                "title": post.title,
                "content": post.content,
                "remove_image": str(first_image.pk),
            },
        )

        self.assertEqual(edit_response.status_code, 302)
        self.assertEqual(post.images.count(), 1)
        self.assertFalse(storage.exists(file_name))
        remaining = post.images.get()
        storage = remaining.image.storage
        remaining_name = remaining.image.name
        self.client.post(reverse("discussion:post_delete", args=(post.pk,)))
        self.assertFalse(storage.exists(remaining_name))
    def test_post_images_are_served_only_to_members(self):
        self.client.force_login(self.member)
        self.client.post(
            reverse("discussion:post_new", args=(self.board.pk,)),
            {
                "title": "Guarded photos",
                "content": "Photo body.",
                "images": [png_upload("guarded.png")],
            },
        )
        image = PostImage.objects.get()
        url = reverse("discussion:post_image", args=(image.pk,))

        member_response = self.client.get(url)
        self.assertEqual(member_response.status_code, 200)
        self.assertEqual(
            member_response.headers["Content-Type"].split(";")[0], "image/png"
        )

        self.client.logout()
        guest_response = self.client.get(url)
        self.assertEqual(guest_response.status_code, 302)
        self.assertIn(reverse("accounts:login"), guest_response["Location"])

        self.assertEqual(
            self.client.get(
                reverse("discussion:post_image", args=(99999,))
            ).status_code,
            302,
        )

        self.client.force_login(self.member)
        self.assertEqual(
            self.client.get(
                reverse("discussion:post_image", args=(99999,))
            ).status_code,
            404,
        )
    def test_post_delete_is_post_only_and_admin_can_delete_any_post(self):
        post = self._post(author=self.member)
        self.client.force_login(self.member)

        get_response = self.client.get(
            reverse("discussion:post_delete", args=(post.pk,))
        )
        self.assertEqual(get_response.status_code, 405)
        delete_response = self.client.post(
            reverse("discussion:post_delete", args=(post.pk,))
        )
        self.assertRedirects(
            delete_response,
            reverse("discussion:board", args=(self.board.pk,)),
        )
        self.assertFalse(Post.objects.filter(pk=post.pk).exists())

        another_post = self._post(author=self.other_member)
        self.client.force_login(self.staff)
        delete_response = self.client.post(
            reverse("discussion:post_delete", args=(another_post.pk,))
        )
        self.assertRedirects(
            delete_response,
            reverse("discussion:board", args=(self.board.pk,)),
        )
        self.assertFalse(Post.objects.filter(pk=another_post.pk).exists())
    def test_invalid_pin_state_is_rejected(self):
        post = self._post()
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("discussion:post_pin", args=(post.pk,)),
            {"is_pinned": "yes"},
        )

        self.assertEqual(response.status_code, 400)
        post.refresh_from_db()
        self.assertFalse(post.is_pinned)
