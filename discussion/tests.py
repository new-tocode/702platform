from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
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


class DiscussionViewTests(TestCase):
    def setUp(self):
        self.member = self._make_user("discussion-view-member")
        self.other_member = self._make_user("discussion-view-other")
        self.staff = self._make_user("discussion-view-staff", is_staff=True)
        self.superuser = User.objects.create_superuser(
            username="discussion-view-superuser",
            password="Super-Password-123!",
        )
        self.board = Board.objects.create(
            name="View Tests",
            created_by=self.superuser,
        )

    def _make_user(self, username, **fields):
        user = User.objects.create_user(
            username=username,
            password="Member-Password-123!",
            **fields,
        )
        user.must_change_password = False
        user.save(update_fields=["must_change_password"])
        return user

    def _post(self, *, author=None, title="A view test post"):
        return Post.objects.create(
            board=self.board,
            author=author or self.member,
            title=title,
            content="The post body.",
        )

    def test_anonymous_and_forced_password_change_users_cannot_view_space(self):
        response = self.client.get(reverse("discussion:space"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])
        board_response = self.client.get(
            reverse("discussion:board", args=(self.board.pk,))
        )
        self.assertEqual(board_response.status_code, 302)
        self.assertIn(reverse("accounts:login"), board_response["Location"])

        self.member.must_change_password = True
        self.member.save(update_fields=["must_change_password"])
        self.client.force_login(self.member)
        response = self.client.get(reverse("discussion:space"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:password_change"), response["Location"])

    def test_member_can_view_space_and_board_but_not_board_management_controls(self):
        self.client.force_login(self.member)

        space_response = self.client.get(reverse("discussion:space"))
        board_response = self.client.get(
            reverse("discussion:board", args=(self.board.pk,))
        )

        self.assertEqual(space_response.status_code, 200)
        self.assertContains(space_response, "View Tests")
        self.assertEqual(board_response.status_code, 200)
        self.assertNotContains(board_response, reverse("discussion:board_create"))
        self.assertNotContains(board_response, "删除空板块")

    def test_member_directory_searches_names_and_links_to_read_only_profiles(self):
        self.member.profile.full_name = "Alex Chen"
        self.member.profile.save(update_fields=["full_name"])
        self.other_member.profile.full_name = "Sam Lee"
        self.other_member.profile.save(update_fields=["full_name"])
        self.client.force_login(self.member)

        response = self.client.get(reverse("discussion:space"), {"q": "alex"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            reverse("accounts:member_profile", args=(self.member.pk,)),
        )
        self.assertContains(response, "Alex Chen")
        self.assertNotContains(response, "Sam Lee")
        self.assertNotContains(response, self.other_member.username)

        username_search = self.client.get(
            reverse("discussion:space"),
            {"q": self.other_member.username},
        )
        self.assertContains(username_search, "没有找到匹配的成员。")
        self.assertNotContains(
            username_search,
            reverse("accounts:member_profile", args=(self.other_member.pk,)),
        )

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

    def test_only_superuser_can_create_or_delete_boards_from_the_frontend(self):
        create_url = reverse("discussion:board_create")
        self.client.force_login(self.member)
        self.assertEqual(
            self.client.post(create_url, {"name": "Member Board"}).status_code,
            403,
        )
        self.client.force_login(self.staff)
        self.assertEqual(
            self.client.post(create_url, {"name": "Staff Board"}).status_code,
            403,
        )

        self.client.force_login(self.superuser)
        create_response = self.client.post(create_url, {"name": "New Board"})
        new_board = Board.objects.get(name="New Board")
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
