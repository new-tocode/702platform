from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from .forms import BoardForm, CommentForm, PostForm
from .models import Board, Comment, Post
from .selectors import member_directory, posts_for_board
from .services import (
    BoardNameTaken,
    BoardNotEmpty,
    create_board,
    create_comment,
    create_post,
    delete_board,
    delete_post,
    set_post_pinned,
    update_post,
)


User = get_user_model()


class DiscussionModelTests(TestCase):
    def setUp(self):
        self.member = User.objects.create_user(
            username="discussion-model-member",
            password="Member-Password-123!",
        )
        self.board = Board.objects.create(
            name="Open Lab",
            created_by=self.member,
        )

    def test_board_names_are_unique_without_case_sensitivity(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Board.objects.create(
                    name="open lab",
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
            name="Research Room",
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
            name="Empty Board",
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

    def test_only_superuser_can_create_and_delete_boards(self):
        with self.assertRaises(PermissionDenied):
            create_board(name="Members Lounge", actor=self.staff)
        with self.assertRaises(PermissionDenied):
            delete_board(board_id=self.board.pk, actor=self.staff)
        with self.assertRaises(PermissionDenied):
            create_board(name="Members Lounge", actor=self.member)

        board = create_board(name="Members Lounge", actor=self.superuser)
        delete_board(board_id=board.pk, actor=self.superuser)
        self.assertFalse(Board.objects.filter(pk=board.pk).exists())

    def test_board_deletion_requires_all_posts_to_be_removed(self):
        self._post()

        with self.assertRaises(BoardNotEmpty):
            delete_board(board_id=self.board.pk, actor=self.superuser)

        self.assertTrue(Board.objects.filter(pk=self.board.pk).exists())

    def test_duplicate_board_name_is_reported_as_domain_error(self):
        with self.assertRaises(BoardNameTaken):
            create_board(name="research room", actor=self.superuser)

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


class DiscussionFormTests(TestCase):
    def test_board_form_accepts_english_names_and_rejects_other_scripts(self):
        self.assertTrue(BoardForm(data={"name": "Open Lab 702"}).is_valid())
        form = BoardForm(data={"name": "社团讨论"})
        self.assertFalse(form.is_valid())
        self.assertIn("name", form.errors)

    def test_post_and_comment_forms_require_nonblank_content(self):
        post_form = PostForm(data={"title": "A title", "content": "  "})
        comment_form = CommentForm(data={"content": "  "})

        self.assertFalse(post_form.is_valid())
        self.assertFalse(comment_form.is_valid())


class DiscussionSelectorTests(TestCase):
    def setUp(self):
        self.member = User.objects.create_user(
            username="directory-alex",
            password="Member-Password-123!",
        )
        self.member.must_change_password = False
        self.member.save(update_fields=["must_change_password"])
        self.member.profile.full_name = "Alex Chen"
        self.member.profile.save(update_fields=["full_name"])

        self.other_member = User.objects.create_user(
            username="directory-sam",
            password="Member-Password-123!",
        )
        self.other_member.must_change_password = False
        self.other_member.save(update_fields=["must_change_password"])
        self.other_member.profile.full_name = "Sam Lee"
        self.other_member.profile.save(update_fields=["full_name"])

        self.inactive = User.objects.create_user(
            username="directory-inactive",
            password="Member-Password-123!",
            is_active=False,
        )

    def test_member_directory_filters_by_name_and_excludes_inactive_accounts(self):
        members = list(member_directory(name_query="alex"))

        self.assertEqual([member.pk for member in members], [self.member.pk])
        self.assertNotIn(self.inactive.pk, [member.pk for member in member_directory()])

    def test_post_selector_prefetches_comments_and_related_profiles(self):
        board = Board.objects.create(name="Directory Board", created_by=self.member)
        post = Post.objects.create(
            board=board,
            author=self.member,
            title="Read the thread",
            content="Thread content.",
        )
        Comment.objects.create(post=post, author=self.other_member, content="A reply.")

        selected = posts_for_board(board).get(pk=post.pk)

        with self.assertNumQueries(0):
            list(selected.comments.all())
            selected.author.profile.full_name
            selected.comments.all()[0].author.profile.full_name
