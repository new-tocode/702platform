"""发言频率：发帖与评论合计，每分钟不超过上限。

上限挡的主要不是帖子本身，而是 @提及——帖子或评论里提到谁，就会给谁写一条
站内消息（``notices.services.sync_mention_messages``），那是站内唯一能主动向
任意成员投递内容的通道。没有上限时，一个账号就能用它刷遍全社。

阈值从 ``services`` 里读，不写死数字：改配置时这里的用例应当跟着走，而不是
变成假绿。
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from ..models import Board, Comment, Post
from ..services import (
    SPEAKING_RATE_LIMIT,
    DiscussionError,
    create_comment,
    create_post,
)


User = get_user_model()


class SpeakingRateLimitTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username="rate-superuser",
            password="Super-Password-123!",
        )
        self.member = User.objects.create_user(
            username="rate-member",
            password="Member-Password-123!",
        )
        self.member.must_change_password = False
        self.member.save(update_fields=["must_change_password"])
        self.board = Board.objects.create(
            name_zh="限速测试",
            name="Rate Tests",
            created_by=self.superuser,
        )
        self.post = Post.objects.create(
            board=self.board,
            author=self.superuser,
            title="被评论的帖子",
            content="正文。",
        )

    def _post(self, *, title="限速用帖子"):
        return create_post(
            board_id=self.board.pk,
            title=title,
            content="正文。",
            actor=self.member,
        )

    def _comment(self):
        return create_comment(
            post_id=self.post.pk,
            content="一条评论。",
            actor=self.member,
        )

    def test_below_the_limit_still_works(self):
        for _ in range(SPEAKING_RATE_LIMIT - 1):
            self._comment()

        self._comment()  # 上限之内的最后一条：应当成功

        self.assertEqual(
            Comment.objects.filter(author=self.member).count(),
            SPEAKING_RATE_LIMIT,
        )

    def test_posting_beyond_the_limit_is_refused(self):
        for _ in range(SPEAKING_RATE_LIMIT):
            self._comment()

        with self.assertRaises(DiscussionError) as caught:
            self._post()

        self.assertIn("发言过于频繁", str(caught.exception))

    def test_posts_and_comments_share_one_budget(self):
        """发帖与评论合计一个额度：只刷评论也不能绕开。"""
        for _ in range(SPEAKING_RATE_LIMIT):
            self._comment()

        with self.assertRaises(DiscussionError):
            self._comment()

    def test_deleted_comments_still_count(self):
        """删掉再发不算绕过——否则「发满、删光、继续发」就是免费的。

        已删除的评论仍在库里（软删除），计数用 ``all_objects`` 把它们算进来。
        """
        for _ in range(SPEAKING_RATE_LIMIT):
            comment = self._comment()
            comment.soft_delete(actor=self.member)

        self.assertEqual(
            Comment.objects.filter(author=self.member).count(),
            0,
            "前置条件：评论应当都已软删除",
        )
        with self.assertRaises(DiscussionError):
            self._comment()

    def test_other_members_are_not_affected(self):
        """限速按人算，一个人刷满了不该牵连别人。"""
        for _ in range(SPEAKING_RATE_LIMIT):
            self._comment()

        other = User.objects.create_user(
            username="rate-other",
            password="Member-Password-123!",
        )
        other.must_change_password = False
        other.save(update_fields=["must_change_password"])

        created = create_comment(
            post_id=self.post.pk,
            content="别人的一条评论。",
            actor=other,
        )

        self.assertEqual(created.author, other)
