"""@ 提及：解析规则，以及消息的写入、对齐与撤回。"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from notices.models import Message

from ..mentions import extract_mentions
from ..models import Board, Post
from ..services import create_comment, create_post, delete_comment, delete_post, update_post


User = get_user_model()


def make_user(*, username, full_name=""):
    user = User.objects.create_user(username=username, password="Member-Password-123!")
    user.must_change_password = False
    user.save(update_fields=["must_change_password"])
    if full_name:
        user.profile.full_name = full_name
        user.profile.save(update_fields=["full_name"])
    return user


class MentionParsingTests(TestCase):
    """解析只看人名：账号名不算，邮箱里的 @ 不算，长的名字优先。"""

    def setUp(self):
        self.zhang = make_user(username="mention-zhang", full_name="张三")
        self.zhangsanfeng = make_user(username="mention-zsf", full_name="张三丰")
        self.li = make_user(username="mention-li", full_name="李四")

    def names_of(self, text):
        return [user.profile.full_name for user in extract_mentions(text)]

    def test_finds_a_name_after_at(self):
        self.assertEqual(self.names_of("请 @张三 看一下"), ["张三"])

    def test_ignores_a_name_without_at(self):
        self.assertEqual(self.names_of("张三 看一下"), [])

    def test_ignores_email_addresses(self):
        self.assertEqual(self.names_of("发到 zhang@example.com 就行"), [])

    def test_longest_name_wins(self):
        self.assertEqual(self.names_of("@张三丰 收"), ["张三丰"])

    def test_short_name_still_matches_when_longer_one_is_absent(self):
        self.assertEqual(self.names_of("@李四光 收"), ["李四"])

    def test_username_is_not_a_name(self):
        self.assertEqual(self.names_of("@mention-zhang 收"), [])

    def test_duplicates_collapse(self):
        self.assertEqual(self.names_of("@张三 @张三"), ["张三"])

    def test_same_name_reaches_every_holder(self):
        other_zhang = make_user(username="mention-zhang-2", full_name="张三")

        mentioned = extract_mentions("请 @张三 看一下")

        self.assertEqual({user.pk for user in mentioned}, {self.zhang.pk, other_zhang.pk})


class MentionMessageTests(TestCase):
    """消息跟着文本走：发帖/评论写消息，编辑对齐，删除撤回。"""

    def setUp(self):
        self.author = make_user(username="mention-author", full_name="作者甲")
        self.target = make_user(username="mention-target", full_name="被提及者")
        self.other = make_user(username="mention-other", full_name="另一位")
        self.board = Board.objects.create(
            name_zh="提及测试", name="Mention Tests", created_by=self.author
        )

    def messages_for(self, user):
        return Message.objects.filter(recipient=user, kind=Message.MENTION)

    def test_creating_a_post_notifies_the_mentioned(self):
        post = create_post(
            board_id=self.board.pk,
            title="标题",
            content="请 @被提及者 看看",
            actor=self.author,
        )

        message = self.messages_for(self.target).get()
        self.assertEqual(message.actor, self.author)
        self.assertEqual(message.post, post)
        self.assertIsNone(message.comment)
        self.assertFalse(message.is_read)

    def test_mention_twice_in_one_post_is_one_message(self):
        create_post(
            board_id=self.board.pk,
            title="标题",
            content="@被提及者 开头，@被提及者 结尾",
            actor=self.author,
        )

        self.assertEqual(self.messages_for(self.target).count(), 1)

    def test_self_mention_does_not_notify(self):
        create_post(
            board_id=self.board.pk,
            title="标题",
            content="@作者甲 自言自语",
            actor=self.author,
        )

        self.assertFalse(self.messages_for(self.author).exists())

    def test_editing_a_post_adds_and_removes_messages(self):
        post = create_post(
            board_id=self.board.pk,
            title="标题",
            content="请 @被提及者 看看",
            actor=self.author,
        )

        update_post(
            post_id=post.pk,
            title="标题",
            content="改请 @另一位 看看",
            actor=self.author,
        )

        self.assertFalse(self.messages_for(self.target).exists())
        self.assertTrue(self.messages_for(self.other).exists())

    def test_a_comment_mention_carries_the_comment(self):
        post = Post.objects.create(
            board=self.board, author=self.author, title="帖子", content="正文"
        )

        comment = create_comment(
            post_id=post.pk,
            content="回复 @被提及者",
            actor=self.author,
        )

        message = self.messages_for(self.target).get()
        self.assertEqual(message.comment, comment)
        self.assertEqual(message.post, post)

    def test_soft_deleting_a_comment_removes_its_mention_message(self):
        post = Post.objects.create(
            board=self.board, author=self.author, title="帖子", content="正文"
        )
        create_comment(post_id=post.pk, content="回复 @被提及者", actor=self.author)

        delete_comment(comment_id=post.comments.get().pk, actor=self.author)

        self.assertFalse(self.messages_for(self.target).exists())

    def test_deleting_a_post_removes_its_mention_messages(self):
        post = create_post(
            board_id=self.board.pk,
            title="标题",
            content="请 @被提及者 看看",
            actor=self.author,
        )

        delete_post(post_id=post.pk, actor=self.author)

        self.assertFalse(self.messages_for(self.target).exists())

    def test_message_row_points_at_the_post_with_a_page_and_anchor(self):
        from notices.selectors import message_rows

        post = create_post(
            board_id=self.board.pk,
            title="标题",
            content="请 @被提及者 看看",
            actor=self.author,
        )

        row = next(
            row for row in message_rows(self.target) if row.title == "标题"
        )

        self.assertEqual(row.type_label, "提及")
        self.assertEqual(row.actor, "作者甲")
        self.assertEqual(row.context, "帖子")
        self.assertEqual(
            row.url,
            reverse(
                "member_notices:message_go",
                args=(self.messages_for(self.target).get().pk,),
            ),
        )
        self.assertTrue(post.pk)
