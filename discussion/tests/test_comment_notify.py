"""评论通知：别人评论你的帖子，帖子作者在「我的消息」里收到一条。

与 ``test_mentions.py`` 的分工：那边管「@ 到谁就给谁发」，这边管「帖主收一条」，
以及两者在同一条评论上相遇时的去重。
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from notices.models import Message
from notices.selectors import message_rows, message_target_url, unread_message_count

from ..models import Board
from ..services import create_comment, create_post, delete_comment, delete_post


User = get_user_model()


def make_user(*, username, full_name=""):
    user = User.objects.create_user(username=username, password="Member-Password-123!")
    user.must_change_password = False
    user.save(update_fields=["must_change_password"])
    if full_name:
        user.profile.full_name = full_name
        user.profile.save(update_fields=["full_name"])
    return user


class CommentNotificationTests(TestCase):
    """收件人是帖子作者；自己评论自己的帖子、以及已经 @ 到作者时都不发。"""

    def setUp(self):
        self.author = make_user(username="cnotify-author", full_name="作者甲")
        self.commenter = make_user(username="cnotify-commenter", full_name="路人乙")
        self.bystander = make_user(username="cnotify-bystander", full_name="旁观丙")
        self.board = Board.objects.create(
            name_zh="评论通知", name="Comment Notify", created_by=self.author
        )
        self.post = create_post(
            board_id=self.board.pk,
            title="一篇帖子",
            content="正文没有提到任何人",
            actor=self.author,
        )

    def messages_for(self, user):
        return Message.objects.filter(recipient=user, kind=Message.COMMENT)

    def comment(self, *, content="写得不错！", actor=None):
        return create_comment(
            post_id=self.post.pk, content=content, actor=actor or self.commenter
        )

    def test_commenting_on_someone_elses_post_notifies_the_author(self):
        comment = self.comment()

        message = self.messages_for(self.author).get()
        self.assertEqual(message.actor, self.commenter)
        self.assertEqual(message.post, self.post)
        self.assertEqual(message.comment, comment)
        self.assertFalse(message.is_read)
        # 评论人自己什么也不该收到。
        self.assertFalse(Message.objects.filter(recipient=self.commenter).exists())

    def test_commenting_on_your_own_post_does_not_notify(self):
        self.comment(actor=self.author)

        self.assertFalse(self.messages_for(self.author).exists())

    def test_each_comment_gets_its_own_message(self):
        first = self.comment(content="第一条")
        second = self.comment(content="第二条")

        self.assertEqual(
            set(self.messages_for(self.author).values_list("comment_id", flat=True)),
            {first.pk, second.pk},
        )

    def test_mentioning_the_author_does_not_add_a_second_message(self):
        self.comment(content="请 @作者甲 看一下")

        messages = Message.objects.filter(recipient=self.author)
        self.assertEqual(messages.count(), 1)
        self.assertEqual(messages.get().kind, Message.MENTION)

    def test_a_mention_in_one_comment_does_not_silence_the_next(self):
        """去重只按「同一条评论」算：前一条 @ 过帖主，不影响后一条。"""
        self.comment(content="请 @作者甲 看一下")
        self.comment(content="再补一句")

        kinds = sorted(
            Message.objects.filter(recipient=self.author).values_list(
                "kind", flat=True
            )
        )
        self.assertEqual(kinds, [Message.COMMENT, Message.MENTION])

    def test_mentioning_someone_else_still_notifies_the_author(self):
        self.comment(content="请 @旁观丙 看一下")

        self.assertEqual(self.messages_for(self.author).get().kind, Message.COMMENT)
        self.assertEqual(
            Message.objects.get(recipient=self.bystander).kind, Message.MENTION
        )

    def test_soft_deleting_a_comment_removes_the_authors_message(self):
        comment = self.comment()

        delete_comment(comment_id=comment.pk, actor=self.commenter)

        self.assertFalse(self.messages_for(self.author).exists())

    def test_deleting_the_post_takes_the_messages_with_it(self):
        self.comment()

        delete_post(post_id=self.post.pk, actor=self.author)

        self.assertFalse(self.messages_for(self.author).exists())


class CommentNotificationRowTests(TestCase):
    """那条消息在「我的消息」里长什么样：类型、标题、来自、状态与落点。"""

    def setUp(self):
        self.author = make_user(username="crow-author", full_name="作者甲")
        self.commenter = make_user(username="crow-commenter", full_name="路人乙")
        self.board = Board.objects.create(
            name_zh="评论通知", name="Comment Notify", created_by=self.author
        )
        self.post = create_post(
            board_id=self.board.pk,
            title="一篇帖子",
            content="正文",
            actor=self.author,
        )

    def comment(self, content):
        return create_comment(
            post_id=self.post.pk, content=content, actor=self.commenter
        )

    def only_row(self):
        rows = [row for row in message_rows(self.author) if row.type_label == "评论"]
        self.assertEqual(len(rows), 1)
        return rows[0]

    def test_row_carries_the_post_title_the_commenter_and_the_excerpt(self):
        self.comment("写得不错！")

        row = self.only_row()

        self.assertEqual(row.title, "一篇帖子")
        self.assertEqual(row.actor, "路人乙")
        self.assertEqual(row.context, "写得不错！")
        self.assertFalse(row.is_read)

    def test_row_counts_as_unread(self):
        self.comment("写得不错！")

        self.assertEqual(unread_message_count(self.author), 1)

    def test_the_excerpt_collapses_whitespace(self):
        self.comment("第一行\n\n第二行    结束")

        self.assertEqual(self.only_row().context, "第一行 第二行 结束")

    def test_a_long_comment_shows_a_truncated_excerpt(self):
        self.comment("太" * 60)

        # 节选连同末尾的省略号一共 40 个字。
        self.assertEqual(self.only_row().context, "太" * 39 + "…")

    def test_row_opens_the_comment_itself(self):
        comment = self.comment("写得不错！")

        target = message_target_url(Message.objects.get(recipient=self.author))

        self.assertEqual(
            target,
            f"{reverse('discussion:board', args=(self.board.pk,))}?page=1"
            f"#comment-{comment.pk}",
        )
