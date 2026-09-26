"""服务层：板块、帖子、评论的写操作与领域异常。"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from core.models import AuditLog
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


User = get_user_model()


class DiscussionServiceTests(TestCase):
    def setUp(self):
        self.member = self._make_member("discussion-member")
        self.other_member = self._make_member("discussion-other")
        self.staff = self._make_member("discussion-staff", is_staff=True)
        self.superuser = User.objects.create_superuser(
            username="discussion-superuser",
            password="Super-Password-123!",
        )
        self.board = Board.objects.create(
            name_zh="研究室", name="Research Room",
            created_by=self.superuser,
        )

    def _make_member(self, username, **fields):
        user = User.objects.create_user(
            username=username,
            password="Member-Password-123!",
            **fields,
        )
        user.must_change_password = False
        user.save(update_fields=["must_change_password"])
        return user

    def _post(self, *, author=None, title="Study group", is_pinned=False):
        return Post.objects.create(
            board=self.board,
            author=author or self.member,
            title=title,
            content="A post body.",
            is_pinned=is_pinned,
        )

    def test_member_can_create_edit_and_delete_own_post(self):
        post = create_post(
            board_id=self.board.pk,
            title="  New thread  ",
            content="  Start here.  ",
            actor=self.member,
        )
        self.assertEqual(post.author, self.member)
        self.assertEqual(post.title, "New thread")
        self.assertEqual(post.content, "Start here.")

        update_post(
            post_id=post.pk,
            title="Updated thread",
            content="Updated body.",
            actor=self.member,
        )
        post.refresh_from_db()
        self.assertEqual(post.title, "Updated thread")
        self.assertEqual(post.content, "Updated body.")

        delete_post(post_id=post.pk, actor=self.member)
        self.assertFalse(Post.objects.filter(pk=post.pk).exists())

    def test_board_mutations_lock_the_board_row(self):
        with CaptureQueriesContext(connection) as captured:
            create_post(
                board_id=self.board.pk,
                title="Lock check",
                content="The board row must be locked.",
                actor=self.member,
            )
        self.assertTrue(
            any(
                "FOR UPDATE" in query["sql"].upper()
                and "DISCUSSION_BOARD" in query["sql"].upper()
                for query in captured.captured_queries
            )
        )

        empty_board = Board.objects.create(
            name_zh="空白板块", name="Empty Board",
            created_by=self.superuser,
        )
        with CaptureQueriesContext(connection) as captured:
            delete_board(board_id=empty_board.pk, actor=self.superuser)
        self.assertTrue(
            any(
                "FOR UPDATE" in query["sql"].upper()
                and "DISCUSSION_BOARD" in query["sql"].upper()
                for query in captured.captured_queries
            )
        )

    def test_member_cannot_edit_or_delete_another_members_post(self):
        post = self._post(author=self.other_member)

        with self.assertRaises(PermissionDenied):
            update_post(
                post_id=post.pk,
                title="Hijacked",
                content="Changed body.",
                actor=self.member,
            )
        with self.assertRaises(PermissionDenied):
            delete_post(post_id=post.pk, actor=self.member)

        post.refresh_from_db()
        self.assertEqual(post.title, "Study group")

    def test_admin_can_delete_another_members_post_and_pin_posts(self):
        post = self._post(author=self.other_member)

        pinned = set_post_pinned(
            post_id=post.pk,
            is_pinned=True,
            actor=self.staff,
        )
        self.assertTrue(pinned.is_pinned)

        delete_post(post_id=post.pk, actor=self.staff)
        self.assertFalse(Post.objects.filter(pk=post.pk).exists())

    def test_member_cannot_pin_or_delete_another_members_post(self):
        post = self._post(author=self.other_member)

        with self.assertRaises(PermissionDenied):
            set_post_pinned(
                post_id=post.pk,
                is_pinned=True,
                actor=self.member,
            )
        with self.assertRaises(PermissionDenied):
            delete_post(post_id=post.pk, actor=self.member)

    def test_member_can_comment_on_another_members_post(self):
        post = self._post(author=self.other_member)

        comment = create_comment(
            post_id=post.pk,
            content="  Useful point.  ",
            actor=self.member,
        )

        self.assertEqual(comment.author, self.member)
        self.assertEqual(comment.content, "Useful point.")

    def test_comment_author_and_admin_can_soft_delete_a_comment(self):
        post = self._post(author=self.other_member)
        own_comment = create_comment(
            post_id=post.pk, content="Mine to remove.", actor=self.member
        )
        other_comment = create_comment(
            post_id=post.pk, content="Not mine.", actor=self.other_member
        )

        board_id, post_id = delete_comment(
            comment_id=own_comment.pk, actor=self.member
        )
        self.assertEqual((board_id, post_id), (self.board.pk, post.pk))
        own_comment.refresh_from_db()
        self.assertIsNotNone(own_comment.deleted_at)
        self.assertEqual(own_comment.deleted_by, self.member)
        # 删除是软删：行与内容都还在，只是不再出现在默认查询里。
        self.assertEqual(own_comment.content, "Mine to remove.")
        self.assertFalse(Comment.objects.filter(pk=own_comment.pk).exists())
        self.assertTrue(Comment.all_objects.filter(pk=own_comment.pk).exists())

        delete_comment(comment_id=other_comment.pk, actor=self.staff)
        other_comment.refresh_from_db()
        self.assertEqual(other_comment.deleted_by, self.staff)

    def test_member_cannot_delete_another_members_comment(self):
        post = self._post(author=self.other_member)
        comment = create_comment(
            post_id=post.pk, content="Someone else's words.", actor=self.other_member
        )

        with self.assertRaises(PermissionDenied):
            delete_comment(comment_id=comment.pk, actor=self.member)

        comment.refresh_from_db()
        self.assertIsNone(comment.deleted_at)
        self.assertTrue(Comment.all_objects.filter(pk=comment.pk).exists())

    def test_deleting_a_comment_twice_keeps_the_first_deletion(self):
        post = self._post(author=self.other_member)
        comment = create_comment(
            post_id=post.pk, content="Delete me once.", actor=self.member
        )

        delete_comment(comment_id=comment.pk, actor=self.member)
        comment.refresh_from_db()
        first_deleted_at, first_deleted_by = (
            comment.deleted_at,
            comment.deleted_by,
        )
        self.assertEqual(
            AuditLog.objects.filter(action="discussion.comment.delete").count(), 1
        )

        # 第二个标签页上的按钮再点一次：不该报错，也不该把留下痕迹的人换成后来者。
        board_id, _post_id = delete_comment(comment_id=comment.pk, actor=self.staff)
        self.assertEqual(board_id, self.board.pk)
        comment.refresh_from_db()
        self.assertEqual(comment.deleted_at, first_deleted_at)
        self.assertEqual(comment.deleted_by, first_deleted_by)
        # 删过这件事只该留一条痕迹，第二次点击不该再写一条说「管理员删了它」。
        self.assertEqual(
            AuditLog.objects.filter(action="discussion.comment.delete").count(), 1
        )

    def test_deleting_a_comment_leaves_the_post_and_its_other_comments_alone(self):
        post = self._post(author=self.other_member)
        kept = create_comment(post_id=post.pk, content="Still here.", actor=self.member)
        removed = create_comment(
            post_id=post.pk, content="Gone soon.", actor=self.member
        )

        delete_comment(comment_id=removed.pk, actor=self.member)

        self.assertTrue(Post.objects.filter(pk=post.pk).exists())
        self.assertEqual(list(post.comments.all()), [kept])

    def test_deleting_a_post_takes_its_soft_deleted_comments_with_it(self):
        post = self._post(author=self.member)
        comment = create_comment(
            post_id=post.pk, content="Deleted, then the post goes.", actor=self.member
        )
        delete_comment(comment_id=comment.pk, actor=self.member)

        # 默认经理过滤掉软删的行，级联删除走的是 _base_manager——两者必须同时成立，
        # 否则删帖会在表里留下一批谁也看不见、谁也删不掉的评论。
        delete_post(post_id=post.pk, actor=self.member)

        self.assertFalse(Comment.all_objects.filter(pk=comment.pk).exists())

    def test_locked_accounts_cannot_delete_comments(self):
        post = self._post(author=self.other_member)
        comment = create_comment(
            post_id=post.pk, content="Protected.", actor=self.member
        )
        self.member.must_change_password = True
        self.member.save(update_fields=["must_change_password"])

        with self.assertRaises(PermissionDenied):
            delete_comment(comment_id=comment.pk, actor=self.member)

        with self.assertRaises(PermissionDenied):
            delete_comment(
                comment_id=create_comment(
                    post_id=post.pk, content="Anonymous.", actor=self.other_member
                ).pk,
                actor=AnonymousUser(),
            )

    def test_only_superuser_can_create_and_delete_boards(self):
        with self.assertRaises(PermissionDenied):
            create_board(name_zh="成员休息室", name="Members Lounge", actor=self.staff)
        with self.assertRaises(PermissionDenied):
            delete_board(board_id=self.board.pk, actor=self.staff)
        with self.assertRaises(PermissionDenied):
            create_board(name_zh="成员休息室", name="Members Lounge", actor=self.member)

        board = create_board(name_zh="成员休息室", name="Members Lounge", actor=self.superuser)
        delete_board(board_id=board.pk, actor=self.superuser)
        self.assertFalse(Board.objects.filter(pk=board.pk).exists())

    def test_board_deletion_requires_all_posts_to_be_removed(self):
        self._post()

        with self.assertRaises(BoardNotEmpty):
            delete_board(board_id=self.board.pk, actor=self.superuser)

        self.assertTrue(Board.objects.filter(pk=self.board.pk).exists())

    def test_duplicate_board_name_is_reported_as_domain_error(self):
        with self.assertRaises(BoardNameTaken):
            create_board(name_zh="研究室", name="research room", actor=self.superuser)

    def test_locked_inactive_and_anonymous_accounts_cannot_use_services(self):
        self.member.must_change_password = True
        self.member.save(update_fields=["must_change_password"])

        with self.assertRaises(PermissionDenied):
            create_post(
                board_id=self.board.pk,
                title="No access",
                content="Locked account.",
                actor=self.member,
            )
        inactive = self._make_member("discussion-inactive")
        inactive.is_active = False
        inactive.save(update_fields=["is_active"])
        with self.assertRaises(PermissionDenied):
            create_post(
                board_id=self.board.pk,
                title="No access",
                content="Inactive account.",
                actor=inactive,
            )
        with self.assertRaises(PermissionDenied):
            create_comment(
                post_id=self._post().pk,
                content="No access.",
                actor=AnonymousUser(),
            )
