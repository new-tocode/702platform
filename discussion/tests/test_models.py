"""模型层：板块、帖子、评论的约束与级联。"""

from datetime import timedelta
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, override_settings
from django.utils import timezone
from ..models import Board, Comment, Post, PostImage


User = get_user_model()


class DiscussionModelTests(TestCase):
    def setUp(self):
        self.member = User.objects.create_user(
            username="discussion-model-member",
            password="Member-Password-123!",
        )
        self.board = Board.objects.create(
            name_zh="开放实验室", name="Open Lab",
            created_by=self.member,
        )

    def test_board_names_are_unique_without_case_sensitivity(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Board.objects.create(
                    name_zh="开放实验室", name="open lab",
                    created_by=self.member,
                )

    def test_empty_board_can_be_deleted(self):
        board_pk = self.board.pk

        self.board.delete()

        self.assertFalse(Board.objects.filter(pk=board_pk).exists())

    def test_posts_are_ordered_pinned_first_then_newest(self):
        older = Post.objects.create(
            board=self.board,
            author=self.member,
            title="Older post",
            content="An older post.",
        )
        newer = Post.objects.create(
            board=self.board,
            author=self.member,
            title="Newer post",
            content="A newer post.",
        )
        pinned = Post.objects.create(
            board=self.board,
            author=self.member,
            title="Pinned post",
            content="A pinned post.",
            is_pinned=True,
        )
        Post.objects.filter(pk=older.pk).update(
            created_at=timezone.now() - timedelta(days=1)
        )

        self.assertEqual(list(self.board.posts.all()), [pinned, newer, older])

    def test_board_cannot_be_deleted_while_posts_exist(self):
        Post.objects.create(
            board=self.board,
            author=self.member,
            title="A discussion",
            content="A post body.",
        )

        with self.assertRaises(ProtectedError):
            self.board.delete()

        self.assertTrue(Board.objects.filter(pk=self.board.pk).exists())

    def test_deleting_post_cascades_to_its_comments(self):
        post = Post.objects.create(
            board=self.board,
            author=self.member,
            title="A discussion",
            content="A post body.",
        )
        comment = Comment.objects.create(
            post=post,
            author=self.member,
            content="A comment.",
        )

        post.delete()

        self.assertFalse(Comment.objects.filter(pk=comment.pk).exists())

    def test_soft_deleted_comments_are_hidden_by_the_default_manager(self):
        post = Post.objects.create(
            board=self.board,
            author=self.member,
            title="A discussion",
            content="A post body.",
        )
        kept = Comment.objects.create(
            post=post, author=self.member, content="Still visible."
        )
        removed = Comment.objects.create(
            post=post, author=self.member, content="Deleted by its author."
        )
        removed.soft_delete(actor=self.member)

        # 「已删除的评论不出现在任何地方」是评论表自己的性质。反向关系
        # post.comments 走的正是默认经理，所以这三条断言同源：漏掉过滤，
        # 删掉的评论会从没加过条件的调用点冒出来。
        self.assertEqual(list(Comment.objects.all()), [kept])
        self.assertEqual(list(post.comments.all()), [kept])
        self.assertEqual(
            list(Comment.all_objects.order_by("created_at", "pk")), [kept, removed]
        )
