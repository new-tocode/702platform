"""只读查询：板块分页、成员目录。"""

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from ..models import Board, Comment, Post, PostImage
from ..selectors import member_directory, posts_for_board


User = get_user_model()


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
        board = Board.objects.create(name_zh="目录板块", name="Directory Board", created_by=self.member)
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
