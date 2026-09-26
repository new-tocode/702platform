"""板块：只有超级管理员能从前台建／删，非空板块删不掉。"""

from django.contrib.auth import get_user_model
from django.urls import reverse
from ..models import Board, Comment, Post, PostImage
from .base import DiscussionViewTestCase


class BoardViewTests(DiscussionViewTestCase):
    def test_only_superuser_can_create_or_delete_boards_from_the_frontend(self):
        create_url = reverse("discussion:board_create")
        self.client.force_login(self.member)
        self.assertEqual(
            self.client.post(create_url, {"name_zh": "成员板块", "name": "Member Board"}).status_code,
            403,
        )
        self.client.force_login(self.staff)
        self.assertEqual(
            self.client.post(create_url, {"name_zh": "管理员板块", "name": "Staff Board"}).status_code,
            403,
        )

        self.client.force_login(self.superuser)
        create_response = self.client.post(create_url, {"name_zh": "新板块", "name": "New Board"})
        new_board = Board.objects.get(name="New Board")
        self.assertEqual(new_board.name_zh, "新板块")
        self.assertRedirects(
            create_response,
            reverse("discussion:board", args=(new_board.pk,)),
        )

        delete_url = reverse("discussion:board_delete", args=(new_board.pk,))
        self.assertEqual(self.client.get(delete_url).status_code, 405)
        delete_response = self.client.post(delete_url)
        self.assertRedirects(delete_response, reverse("discussion:space"))
        self.assertFalse(Board.objects.filter(pk=new_board.pk).exists())
    def test_nonempty_board_cannot_be_deleted_and_unknown_objects_are_404(self):
        post = self._post()
        self.client.force_login(self.superuser)

        response = self.client.post(
            reverse("discussion:board_delete", args=(self.board.pk,))
        )
        self.assertRedirects(
            response,
            reverse("discussion:board", args=(self.board.pk,)),
        )
        self.assertTrue(Board.objects.filter(pk=self.board.pk).exists())
        self.assertTrue(Post.objects.filter(pk=post.pk).exists())

        self.assertEqual(
            self.client.get(reverse("discussion:board", args=(99999,))).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                reverse("discussion:post_delete", args=(99999,))
            ).status_code,
            404,
        )
