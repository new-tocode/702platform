"""评论：发表、置顶、软删除，以及删除后从页面与计数里消失。"""

from django.contrib.auth import get_user_model
from django.urls import reverse
from ..models import Board, Comment, Post, PostImage
from .base import DiscussionViewTestCase


class CommentViewTests(DiscussionViewTestCase):
    def test_member_can_comment_and_only_admin_can_pin(self):
        post = self._post(author=self.other_member)
        self.client.force_login(self.member)

        comment_response = self.client.post(
            reverse("discussion:comment_create", args=(post.pk,)),
            {"content": "A member reply."},
        )
        self.assertRedirects(
            comment_response,
            reverse("discussion:board", args=(self.board.pk,)),
        )
        self.assertEqual(post.comments.get().author, self.member)

        pin_url = reverse("discussion:post_pin", args=(post.pk,))
        self.assertEqual(self.client.get(pin_url).status_code, 405)
        self.assertEqual(
            self.client.post(pin_url, {"is_pinned": "true"}).status_code,
            403,
        )

        self.client.force_login(self.staff)
        pin_response = self.client.post(pin_url, {"is_pinned": "true"})
        self.assertRedirects(
            pin_response,
            reverse("discussion:board", args=(self.board.pk,)),
        )
        post.refresh_from_db()
        self.assertTrue(post.is_pinned)

        unpin_response = self.client.post(pin_url, {"is_pinned": "false"})
        self.assertEqual(unpin_response.status_code, 302)
        post.refresh_from_db()
        self.assertFalse(post.is_pinned)
    def test_comment_delete_button_is_only_shown_to_author_and_admin(self):
        self.other_member.profile.full_name = "Sam Lee"
        self.other_member.profile.save(update_fields=["full_name"])
        post = self._post(author=self.other_member)
        comment = Comment.objects.create(
            post=post, author=self.other_member, content="Written by Sam."
        )
        delete_url = reverse("discussion:comment_delete", args=(comment.pk,))

        self.client.force_login(self.member)
        board_page = self.client.get(
            reverse("discussion:board", args=(self.board.pk,))
        )
        self.assertContains(board_page, "Written by Sam.")
        self.assertNotContains(board_page, delete_url)

        self.client.force_login(self.other_member)
        self.assertContains(
            self.client.get(reverse("discussion:board", args=(self.board.pk,))),
            delete_url,
        )

        # 管理员对别人的评论也有入口。
        self.client.force_login(self.staff)
        self.assertContains(
            self.client.get(reverse("discussion:board", args=(self.board.pk,))),
            delete_url,
        )
    def test_comment_delete_is_post_only_and_scoped_to_the_author(self):
        post = self._post(author=self.other_member)
        own_comment = Comment.objects.create(
            post=post, author=self.member, content="Mine."
        )
        other_comment = Comment.objects.create(
            post=post, author=self.other_member, content="Theirs."
        )
        own_url = reverse("discussion:comment_delete", args=(own_comment.pk,))
        other_url = reverse("discussion:comment_delete", args=(other_comment.pk,))
        self.client.force_login(self.member)

        self.assertEqual(self.client.get(own_url).status_code, 405)
        self.assertEqual(self.client.post(other_url).status_code, 403)
        self.assertIsNone(
            Comment.all_objects.get(pk=other_comment.pk).deleted_at
        )

        delete_response = self.client.post(own_url)
        self.assertRedirects(
            delete_response,
            reverse("discussion:board", args=(self.board.pk,)),
        )
        self.assertFalse(Comment.objects.filter(pk=own_comment.pk).exists())
        own_comment.refresh_from_db()
        self.assertIsNotNone(own_comment.deleted_at)

        # 管理员删别人的评论。
        self.client.force_login(self.staff)
        admin_response = self.client.post(other_url)
        self.assertRedirects(
            admin_response,
            reverse("discussion:board", args=(self.board.pk,)),
        )
        other_comment.refresh_from_db()
        self.assertIsNotNone(other_comment.deleted_at)
    def test_deleted_comment_disappears_from_the_page_and_count(self):
        post = self._post(author=self.other_member)
        comment = Comment.objects.create(
            post=post, author=self.member, content="Please forget this line."
        )
        self.client.force_login(self.member)

        before = self.client.get(reverse("discussion:board", args=(self.board.pk,)))
        self.assertContains(before, "Please forget this line.")
        self.assertEqual(before.context["posts_page"][0].comments.count(), 1)

        self.client.post(reverse("discussion:comment_delete", args=(comment.pk,)))

        after = self.client.get(reverse("discussion:board", args=(self.board.pk,)))
        self.assertNotContains(after, "Please forget this line.")
        self.assertContains(after, "还没有评论。")
        # 计数与已删除的评论一起走——留着数字对不上列表，看着像丢了行。
        self.assertEqual(after.context["posts_page"][0].comments.count(), 0)
    def test_deleting_a_comment_keeps_the_post_and_its_other_comments(self):
        post = self._post(author=self.other_member)
        kept = Comment.objects.create(post=post, author=self.member, content="Keep me.")
        removed = Comment.objects.create(
            post=post, author=self.member, content="Drop me."
        )
        self.client.force_login(self.member)

        self.client.post(
            reverse("discussion:comment_delete", args=(removed.pk,))
        )

        page = self.client.get(reverse("discussion:board", args=(self.board.pk,)))
        self.assertContains(page, "Keep me.")
        self.assertNotContains(page, "Drop me.")
        self.assertTrue(Post.objects.filter(pk=post.pk).exists())
        self.assertTrue(Comment.objects.filter(pk=kept.pk).exists())
    def test_unknown_comment_is_404_and_locked_accounts_are_redirected(self):
        self.client.force_login(self.member)
        self.assertEqual(
            self.client.post(
                reverse("discussion:comment_delete", args=(99999,))
            ).status_code,
            404,
        )

        post = self._post(author=self.other_member)
        comment = Comment.objects.create(
            post=post, author=self.member, content="Locked out."
        )
        self.member.must_change_password = True
        self.member.save(update_fields=["must_change_password"])
        locked_response = self.client.post(
            reverse("discussion:comment_delete", args=(comment.pk,))
        )
        self.assertEqual(locked_response.status_code, 302)
        self.assertIn(
            reverse("accounts:password_change"), locked_response["Location"]
        )
        self.assertIsNone(Comment.all_objects.get(pk=comment.pk).deleted_at)
