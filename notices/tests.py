"""Stage 2 acceptance tests for public and internal notices."""

from datetime import timedelta
from urllib.parse import quote

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog
from projects.models import ProjectGroup

from .models import (
    DIRECT_MESSAGE_MAX_CHARS,
    DirectMessage,
    Message,
    Notice,
    NoticeRead,
)
from .selectors import (
    _CONTENT_BUILDERS,
    _TYPE_LABELS,
    message_rows,
    unread_message_count,
)
from .services import (
    mark_all_read,
    mark_message_read,
    mark_read,
    send_direct_message,
)


User = get_user_model()


class NoticeVisibilityAcceptanceTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="notice-admin",
            password="Admin-Password-123!",
        )
        self.member = User.objects.create_user(
            username="notice-member",
            password="Member-Password-123!",
        )
        self.member.must_change_password = False
        self.member.save(update_fields=["must_change_password"])
        self.allowed_group = Group.objects.create(name="竞赛组")
        self.other_group = Group.objects.create(name="宣传组")
        self.member.groups.add(self.allowed_group)
        self.other_member = User.objects.create_user(
            username="notice-other-member",
            password="Other-Password-123!",
        )
        self.other_member.must_change_password = False
        self.other_member.save(update_fields=["must_change_password"])
        self.other_member.groups.add(self.other_group)
        self.no_group_member = User.objects.create_user(
            username="notice-no-group-member",
            password="No-Group-Password-123!",
        )
        self.no_group_member.must_change_password = False
        self.no_group_member.save(update_fields=["must_change_password"])
        self.contact = User.objects.create_user(
            username="notice-contact",
            password="Contact-Password-123!",
        )
        self.contact.must_change_password = False
        self.contact.save(update_fields=["must_change_password"])
        self.contact_group = ProjectGroup.objects.create(
            name="通知项目组",
            leader=self.contact,
        )
        now = timezone.now()
        self.public_notice = Notice.objects.create(
            title="校园公开公告",
            content="访客可以看到的公开内容。",
            scope=Notice.PUBLIC,
            published_by=self.admin,
            published_at=now - timedelta(minutes=2),
        )
        self.internal_notice = Notice.objects.create(
            title="社团内部公告",
            content="成员才可以看到的内部内容。",
            scope=Notice.INTERNAL,
            published_by=self.admin,
            published_at=now - timedelta(minutes=1),
        )
        self.internal_notice.visible_groups.add(self.allowed_group)
        self.contacts_notice = Notice.objects.create(
            title="仅联系人公告",
            content="只有项目组联系人才可以看到。",
            scope=Notice.CONTACTS,
            published_by=self.admin,
            published_at=now,
        )

    def test_anonymous_can_view_public_list_and_detail(self):
        response = self.client.get(reverse("notices:public_list"))
        detail_response = self.client.get(
            reverse("notices:public_detail", args=(self.public_notice.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.public_notice.title)
        self.assertNotContains(response, self.internal_notice.title)
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, self.public_notice.content)

    def test_public_routes_never_expose_internal_notice(self):
        list_response = self.client.get(reverse("notices:public_list"))
        detail_response = self.client.get(
            reverse("notices:public_detail", args=(self.internal_notice.pk,))
        )

        self.assertNotContains(list_response, self.internal_notice.title)
        self.assertEqual(detail_response.status_code, 404)

    def test_anonymous_is_redirected_from_internal_notice_list(self):
        response = self.client.get(reverse("member_notices:internal_list"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def test_unlocked_member_sees_internal_and_public_notices_in_my_messages(self):
        self.client.force_login(self.member)

        list_response = self.client.get(reverse("member_notices:internal_list"))
        detail_response = self.client.get(
            reverse("member_notices:internal_detail", args=(self.internal_notice.pk,))
        )
        public_detail_response = self.client.get(
            reverse("notices:public_detail", args=(self.internal_notice.pk,))
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, self.internal_notice.title)
        # 公开通知也从「我的消息」里走一遍——但它仍然有自己的公告栏，
        # 而公开那条路依然不暴露内部通知（下面两行）。
        self.assertContains(list_response, self.public_notice.title)
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, self.internal_notice.content)
        self.assertEqual(public_detail_response.status_code, 404)

    def test_unmatched_user_group_cannot_view_internal_notice_list_or_detail(self):
        self.client.force_login(self.other_member)

        list_response = self.client.get(reverse("member_notices:internal_list"))
        detail_response = self.client.get(
            reverse("member_notices:internal_detail", args=(self.internal_notice.pk,))
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertNotContains(list_response, self.internal_notice.title)
        self.assertEqual(detail_response.status_code, 404)

    def test_member_without_any_group_cannot_view_internal_notice(self):
        self.client.force_login(self.no_group_member)

        list_response = self.client.get(reverse("member_notices:internal_list"))
        detail_response = self.client.get(
            reverse("member_notices:internal_detail", args=(self.internal_notice.pk,))
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertNotContains(list_response, self.internal_notice.title)
        self.assertEqual(detail_response.status_code, 404)

    def test_member_in_any_selected_group_can_view_internal_notice(self):
        second_group = Group.objects.create(name="另一个可见组")
        self.internal_notice.visible_groups.add(second_group)
        self.member.groups.remove(self.allowed_group)
        self.member.groups.add(second_group)
        self.client.force_login(self.member)

        response = self.client.get(reverse("member_notices:internal_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.internal_notice.title)

    def test_project_contact_can_view_contacts_notice(self):
        self.client.force_login(self.contact)

        list_response = self.client.get(reverse("member_notices:internal_list"))
        detail_response = self.client.get(
            reverse("member_notices:internal_detail", args=(self.contacts_notice.pk,))
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, self.contacts_notice.title)
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, self.contacts_notice.content)

    def test_non_contact_cannot_view_contacts_notice(self):
        self.client.force_login(self.member)

        list_response = self.client.get(reverse("member_notices:internal_list"))
        detail_response = self.client.get(
            reverse("member_notices:internal_detail", args=(self.contacts_notice.pk,))
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertNotContains(list_response, self.contacts_notice.title)
        self.assertEqual(detail_response.status_code, 404)

    def test_public_route_never_exposes_contacts_notice(self):
        response = self.client.get(
            reverse("notices:public_detail", args=(self.contacts_notice.pk,))
        )

        self.assertEqual(response.status_code, 404)

    def test_forced_member_cannot_bypass_password_change_on_internal_route(self):
        self.member.must_change_password = True
        self.member.save(update_fields=["must_change_password"])
        self.client.force_login(self.member)

        response = self.client.get(reverse("member_notices:internal_list"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:password_change"), response["Location"])

    def test_home_shows_only_latest_public_notices(self):
        response = self.client.get(reverse("accounts:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.public_notice.title)
        self.assertNotContains(response, self.internal_notice.title)

    def test_pinned_public_notice_is_sorted_first(self):
        pinned = Notice.objects.create(
            title="年度置顶公告",
            content="置顶公告内容。",
            scope=Notice.PUBLIC,
            is_pinned=True,
            published_by=self.admin,
            published_at=timezone.now() - timedelta(days=1),
        )

        response = self.client.get(reverse("notices:public_list"))

        self.assertEqual(response.status_code, 200)
        self.assertLess(
            response.content.decode().index(pinned.title),
            response.content.decode().index(self.public_notice.title),
        )


class MessageReadStateTests(TestCase):
    """「我的消息」的数据层：行形状、未读计数、标已读，以及删除通知的连带。

    视图层的验收（列表列、样式、按钮）另有一组，这里只钉数据口径。
    """

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="message-admin",
            password="Admin-Password-123!",
        )
        self.admin.profile.full_name = "通知管理员"
        self.admin.profile.save(update_fields=["full_name"])
        self.member = User.objects.create_user(
            username="message-member",
            password="Member-Password-123!",
        )
        self.member.must_change_password = False
        self.member.save(update_fields=["must_change_password"])
        self.group = Group.objects.create(name="消息可见组")
        self.member.groups.add(self.group)
        self.contact = User.objects.create_user(
            username="message-contact",
            password="Contact-Password-123!",
        )
        self.contact.must_change_password = False
        self.contact.save(update_fields=["must_change_password"])
        ProjectGroup.objects.create(name="消息项目组", leader=self.contact)

        now = timezone.now()
        self.internal_notice = Notice.objects.create(
            title="发到消息组的通知",
            content="正文。",
            scope=Notice.INTERNAL,
            published_by=self.admin,
            published_at=now - timedelta(minutes=1),
        )
        self.internal_notice.visible_groups.add(self.group)
        self.contacts_notice = Notice.objects.create(
            title="只发给联系人的通知",
            content="正文。",
            scope=Notice.CONTACTS,
            published_by=self.admin,
            published_at=now,
        )
        self.hidden_notice = Notice.objects.create(
            title="别的组的通知",
            content="正文。",
            scope=Notice.INTERNAL,
            published_by=self.admin,
            published_at=now - timedelta(minutes=2),
        )
        self.hidden_notice.visible_groups.add(Group.objects.create(name="别的组"))

    def test_rows_only_include_notices_visible_to_that_user(self):
        member_rows = message_rows(self.member)
        contact_rows = message_rows(self.contact)

        self.assertEqual(
            [row.title for row in member_rows],
            ["发到消息组的通知"],
        )
        self.assertEqual(
            [row.title for row in contact_rows],
            ["只发给联系人的通知"],
        )

    def test_row_carries_type_actor_context_and_read_state(self):
        row = message_rows(self.member)[0]

        self.assertEqual(row.type_label, "内部通知")
        self.assertEqual(row.actor, "通知管理员")
        self.assertEqual(row.context, "消息可见组")
        self.assertFalse(row.is_read)
        self.assertEqual(row.url, reverse("member_notices:internal_detail", args=(self.internal_notice.pk,)))

    def test_actor_falls_back_to_username_without_full_name(self):
        self.admin.profile.full_name = ""
        self.admin.profile.save(update_fields=["full_name"])

        row = message_rows(self.member)[0]

        self.assertEqual(row.actor, "message-admin")

    def test_contacts_notice_context_is_the_contacts_phrase(self):
        row = message_rows(self.contact)[0]

        self.assertEqual(row.context, "仅项目组联系人")

    def test_internal_notice_lists_all_visible_group_names(self):
        self.internal_notice.visible_groups.add(Group.objects.create(name="第二个可见组"))

        row = message_rows(self.member)[0]

        self.assertEqual(row.context, "消息可见组, 第二个可见组")

    def test_unread_count_only_counts_visible_unread_notices(self):
        # member 可见 1 条（hidden 那条属于别的组），且尚未读过。
        self.assertEqual(unread_message_count(self.member), 1)

        mark_read(user=self.member, notice=self.internal_notice)

        self.assertEqual(unread_message_count(self.member), 0)

    def test_mark_read_is_idempotent(self):
        self.assertTrue(mark_read(user=self.member, notice=self.internal_notice))
        self.assertFalse(mark_read(user=self.member, notice=self.internal_notice))

        self.assertEqual(
            NoticeRead.objects.filter(user=self.member).count(),
            1,
        )
        self.assertTrue(message_rows(self.member)[0].is_read)

    def test_mark_all_read_marks_only_this_users_visible_notices(self):
        marked = mark_all_read(user=self.member)

        self.assertEqual(marked, 1)
        self.assertEqual(unread_message_count(self.member), 0)
        self.assertEqual(unread_message_count(self.contact), 1)
        self.assertFalse(
            NoticeRead.objects.filter(user=self.member, notice=self.hidden_notice).exists()
        )

    def test_mark_all_read_is_idempotent(self):
        self.assertEqual(mark_all_read(user=self.member), 1)
        self.assertEqual(mark_all_read(user=self.member), 0)

    def test_deleting_a_notice_drops_it_from_rows_count_and_receipts(self):
        mark_read(user=self.member, notice=self.internal_notice)

        self.internal_notice.delete()

        self.assertEqual(message_rows(self.member), ())
        self.assertEqual(unread_message_count(self.member), 0)
        self.assertFalse(NoticeRead.objects.filter(user=self.member).exists())


class EventMessageAggregationTests(TestCase):
    """事件型消息（Message 表）与通知混排：行装配、计数、全部已读、跳转端点。"""

    def setUp(self):
        from discussion.models import Board, Comment, Post

        self.admin = User.objects.create_superuser(
            username="event-admin",
            password="Admin-Password-123!",
        )
        self.member = User.objects.create_user(
            username="event-member",
            password="Member-Password-123!",
        )
        self.member.must_change_password = False
        self.member.save(update_fields=["must_change_password"])
        self.group = Group.objects.create(name="事件组")
        self.member.groups.add(self.group)

        self.notice = Notice.objects.create(
            title="一条内部通知",
            content="正文。",
            scope=Notice.INTERNAL,
            published_by=self.admin,
            published_at=timezone.now() - timedelta(hours=2),
        )
        self.notice.visible_groups.add(self.group)

        self.board = Board.objects.create(
            name_zh="综合区", name="General", created_by=self.admin
        )
        self.post = Post.objects.create(
            board=self.board,
            author=self.admin,
            title="被提及的帖子",
            content="正文",
        )
        self.comment = Comment.objects.create(
            post=self.post, author=self.admin, content="一条评论"
        )
        self.post_message = Message.objects.create(
            recipient=self.member,
            kind=Message.MENTION,
            actor=self.admin,
            post=self.post,
        )
        self.client.force_login(self.member)

    def test_mention_row_carries_actor_context_and_the_go_url(self):
        rows = message_rows(self.member)
        mention = next(row for row in rows if row.title == "被提及的帖子")

        self.assertEqual(mention.type_label, "提及")
        self.assertEqual(mention.actor, "event-admin")
        self.assertEqual(mention.context, "帖子")
        self.assertEqual(
            mention.url,
            reverse("member_notices:message_go", args=(self.post_message.pk,)),
        )
        self.assertFalse(mention.is_read)

    def test_comment_mention_links_to_the_comment_anchor(self):
        comment_message = Message.objects.create(
            recipient=self.member,
            kind=Message.MENTION,
            actor=self.admin,
            post=self.post,
            comment=self.comment,
        )

        response = self.client.get(
            reverse("member_notices:message_go", args=(comment_message.pk,))
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            f"{reverse('discussion:board', args=(self.board.pk,))}?page=1"
            f"#comment-{self.comment.pk}",
        )

    def test_comment_row_carries_the_excerpt_and_links_to_the_comment(self):
        comment_message = Message.objects.create(
            recipient=self.member,
            kind=Message.COMMENT,
            actor=self.admin,
            post=self.post,
            comment=self.comment,
        )

        row = next(row for row in message_rows(self.member) if row.type_label == "评论")

        self.assertEqual(row.title, "被提及的帖子")
        self.assertEqual(row.actor, "event-admin")
        self.assertEqual(row.context, "一条评论")

        response = self.client.get(row.url)

        self.assertEqual(
            response["Location"],
            f"{reverse('discussion:board', args=(self.board.pk,))}?page=1"
            f"#comment-{self.comment.pk}",
        )
        comment_message.refresh_from_db()
        self.assertTrue(comment_message.is_read)

        page = self.client.get(reverse("member_notices:internal_list"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "一条评论")

    def test_rows_sort_pinned_first_then_by_time(self):
        Notice.objects.create(
            title="更新的公开通知",
            content="正文。",
            scope=Notice.PUBLIC,
            published_by=self.admin,
            published_at=timezone.now(),
        )

        titles = [row.title for row in message_rows(self.member)]

        # 公开通知最新，排最前；提及在 2 小时前的内部通知之后。
        self.assertEqual(titles, ["更新的公开通知", "被提及的帖子", "一条内部通知"])

    def test_unread_count_adds_notices_and_event_messages(self):
        self.assertEqual(unread_message_count(self.member), 2)

        mark_message_read(message=self.post_message)

        self.assertEqual(unread_message_count(self.member), 1)

    def test_mark_all_read_clears_both_kinds(self):
        mark_all_read(user=self.member)

        self.assertEqual(unread_message_count(self.member), 0)
        self.post_message.refresh_from_db()
        self.assertTrue(self.post_message.is_read)
        self.assertIsNotNone(self.post_message.read_at)

    def test_message_go_marks_read_and_redirects_to_the_post(self):
        response = self.client.get(
            reverse("member_notices:message_go", args=(self.post_message.pk,))
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            f"{reverse('discussion:board', args=(self.board.pk,))}?page=1"
            f"#post-{self.post.pk}",
        )
        self.post_message.refresh_from_db()
        self.assertTrue(self.post_message.is_read)

    def test_message_go_of_another_recipient_is_404(self):
        other = User.objects.create_user(
            username="event-other",
            password="Other-Password-123!",
        )
        other.must_change_password = False
        other.save(update_fields=["must_change_password"])

        self.client.force_login(other)
        response = self.client.get(
            reverse("member_notices:message_go", args=(self.post_message.pk,))
        )

        self.assertEqual(response.status_code, 404)

    def test_unknown_kind_is_skipped_instead_of_breaking_the_page(self):
        Message.objects.create(
            recipient=self.member,
            kind="from-the-future",
            actor=self.admin,
            post=self.post,
        )

        titles = [row.title for row in message_rows(self.member)]
        response = self.client.get(reverse("member_notices:internal_list"))

        self.assertNotIn("from-the-future", titles)
        self.assertEqual(response.status_code, 200)


class MessageKindCoverageTests(TestCase):
    """一个 kind 要同时出现在三处才能渲染；漏一处以前只能在页面上炸出来。"""

    def test_every_kind_has_a_type_label_and_a_content_builder(self):
        kinds = {kind for kind, _label in Message.KIND_CHOICES}

        self.assertEqual(set(_TYPE_LABELS), kinds)
        self.assertEqual(set(_CONTENT_BUILDERS), kinds)


class MemberHomeReminderAcceptanceTests(TestCase):
    """成员中心上的「我的消息」：入口改名，未读时提醒条与徽标都带计数。"""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="reminder-admin",
            password="Admin-Password-123!",
        )
        self.member = User.objects.create_user(
            username="reminder-member",
            password="Member-Password-123!",
        )
        self.member.must_change_password = False
        self.member.save(update_fields=["must_change_password"])
        self.group = Group.objects.create(name="提醒组")
        self.member.groups.add(self.group)
        self.notice = Notice.objects.create(
            title="提醒用的通知",
            content="正文。",
            scope=Notice.INTERNAL,
            published_by=self.admin,
        )
        self.notice.visible_groups.add(self.group)
        self.client.force_login(self.member)

    def test_entry_is_renamed_and_points_at_the_message_page(self):
        response = self.client.get(reverse("accounts:member_home"))

        self.assertContains(response, "我的消息")
        self.assertContains(response, reverse("member_notices:internal_list"))
        self.assertNotContains(response, "内部通知")

    def test_reminder_bar_and_entry_badge_carry_the_unread_count(self):
        second = Notice.objects.create(
            title="第二条通知",
            content="正文。",
            scope=Notice.INTERNAL,
            published_by=self.admin,
        )
        second.visible_groups.add(self.group)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertContains(response, "2 条未读消息")
        self.assertContains(response, '<span class="entry-badge">2</span>')

    def test_nothing_is_rendered_once_everything_is_read(self):
        mark_read(user=self.member, notice=self.notice)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertContains(response, "我的消息")
        self.assertNotContains(response, "未读消息")
        self.assertNotContains(response, "entry-badge")

    def test_unread_from_other_groups_does_not_trigger_the_reminder(self):
        self.member.groups.clear()

        response = self.client.get(reverse("accounts:member_home"))

        self.assertNotContains(response, "未读消息")
        self.assertNotContains(response, "entry-badge")


class MessagePageAcceptanceTests(TestCase):
    """「我的消息」页：五列、未读样式、点开即已读、全部已读与删除的连带。"""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="message-page-admin",
            password="Admin-Password-123!",
        )
        self.admin.profile.full_name = "通知管理员"
        self.admin.profile.save(update_fields=["full_name"])
        self.member = User.objects.create_user(
            username="message-page-member",
            password="Member-Password-123!",
        )
        self.member.must_change_password = False
        self.member.save(update_fields=["must_change_password"])
        self.group = Group.objects.create(name="消息组")
        self.member.groups.add(self.group)
        now = timezone.now()
        self.pinned_notice = Notice.objects.create(
            title="置顶的消息",
            content="正文。",
            scope=Notice.INTERNAL,
            is_pinned=True,
            published_by=self.admin,
            published_at=now - timedelta(minutes=2),
        )
        self.pinned_notice.visible_groups.add(self.group)
        self.notice = Notice.objects.create(
            title="普通的消息",
            content="正文。",
            scope=Notice.INTERNAL,
            published_by=self.admin,
            published_at=now - timedelta(minutes=1),
        )
        self.notice.visible_groups.add(self.group)
        self.client.force_login(self.member)

    def test_page_shows_the_five_columns_with_type_actor_and_context(self):
        response = self.client.get(reverse("member_notices:internal_list"))
        html = response.content.decode()

        self.assertContains(response, "我的消息")
        for header in ("类型", "标题", "来自", "说明", "时间"):
            self.assertIn(header, html)
        self.assertContains(response, "内部通知")
        self.assertContains(response, "通知管理员")
        self.assertContains(response, "消息组")

    def test_unread_rows_are_highlighted_and_counted(self):
        response = self.client.get(reverse("member_notices:internal_list"))

        self.assertEqual(response.content.decode().count('class="unread"'), 2)
        self.assertContains(response, "2 条未读")

    def test_reading_a_message_clears_its_unread_mark(self):
        self.client.get(
            reverse("member_notices:internal_detail", args=(self.notice.pk,))
        )

        response = self.client.get(reverse("member_notices:internal_list"))

        self.assertEqual(response.content.decode().count('class="unread"'), 1)
        self.assertContains(response, "1 条未读")
        self.assertTrue(
            NoticeRead.objects.filter(user=self.member, notice=self.notice).exists()
        )

    def test_opening_detail_twice_keeps_a_single_receipt(self):
        url = reverse("member_notices:internal_detail", args=(self.notice.pk,))

        self.client.get(url)
        self.client.get(url)

        self.assertEqual(
            NoticeRead.objects.filter(user=self.member, notice=self.notice).count(),
            1,
        )

    def test_mark_all_read_clears_everything_and_reports(self):
        response = self.client.post(
            reverse("member_notices:mark_all_read"), follow=True
        )

        self.assertContains(response, "已将全部消息标为已读。")
        self.assertNotIn('class="unread"', response.content.decode())
        self.assertEqual(unread_message_count(self.member), 0)

    def test_mark_all_read_is_post_only(self):
        response = self.client.get(reverse("member_notices:mark_all_read"))

        self.assertEqual(response.status_code, 405)

    def test_all_read_button_only_shows_while_something_is_unread(self):
        with_unread = self.client.get(reverse("member_notices:internal_list"))
        self.assertContains(with_unread, "全部已读")

        mark_all_read(user=self.member)

        without_unread = self.client.get(reverse("member_notices:internal_list"))
        self.assertNotContains(without_unread, "全部已读")

    def test_deleting_a_notice_removes_it_from_the_page(self):
        self.notice.delete()

        response = self.client.get(reverse("member_notices:internal_list"))

        self.assertNotContains(response, "普通的消息")
        self.assertContains(response, "1 条未读")

    def test_pinned_message_sorts_first(self):
        response = self.client.get(reverse("member_notices:internal_list"))
        html = response.content.decode()

        self.assertLess(html.index("置顶的消息"), html.index("普通的消息"))


class NoticeAdminAcceptanceTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="notice-admin",
            password="Admin-Password-123!",
        )
        self.allowed_group = Group.objects.create(name="管理员指定组")
        self.client.force_login(self.admin)

    def test_admin_can_publish_notice_and_operator_is_recorded(self):
        response = self.client.post(
            reverse("admin:notices_notice_add"),
            {
                "title": "管理员发布的通知",
                "content": "管理员通知正文。",
                "scope": Notice.INTERNAL,
                "visible_groups": [self.allowed_group.pk],
                "is_pinned": "on",
                "_save": "保存",
            },
        )

        self.assertEqual(response.status_code, 302)
        notice = Notice.objects.get(title="管理员发布的通知")
        self.assertEqual(notice.published_by, self.admin)
        self.assertEqual(notice.scope, Notice.INTERNAL)
        self.assertEqual(list(notice.visible_groups.all()), [self.allowed_group])
        self.assertTrue(notice.is_pinned)
        audit = AuditLog.objects.get(action="notices.create")
        self.assertEqual(audit.user, self.admin)
        self.assertEqual(audit.target_id, str(notice.pk))

    def test_admin_cannot_publish_internal_notice_without_visible_group(self):
        response = self.client.post(
            reverse("admin:notices_notice_add"),
            {
                "title": "缺少用户组的内部通知",
                "content": "不应保存。",
                "scope": Notice.INTERNAL,
                "is_pinned": "",
                "_save": "保存",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "内部通知必须至少选择一个可查看用户组")
        self.assertFalse(
            Notice.objects.filter(title="缺少用户组的内部通知").exists()
        )

    def test_admin_cannot_assign_groups_to_public_notice(self):
        response = self.client.post(
            reverse("admin:notices_notice_add"),
            {
                "title": "范围冲突的公开通知",
                "content": "不应保存。",
                "scope": Notice.PUBLIC,
                "visible_groups": [self.allowed_group.pk],
                "is_pinned": "",
                "_save": "保存",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "只有内部通知才需要选择可查看用户组")
        self.assertFalse(Notice.objects.filter(title="范围冲突的公开通知").exists())

    def test_admin_can_publish_contacts_notice_without_group(self):
        response = self.client.post(
            reverse("admin:notices_notice_add"),
            {
                "title": "仅联系人通知",
                "content": "只发给项目组联系人的通知。",
                "scope": Notice.CONTACTS,
                "is_pinned": "",
                "_save": "保存",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Notice.objects.filter(title="仅联系人通知").exists())

    def test_admin_cannot_assign_groups_to_contacts_notice(self):
        response = self.client.post(
            reverse("admin:notices_notice_add"),
            {
                "title": "范围冲突的联系人通知",
                "content": "不应保存。",
                "scope": Notice.CONTACTS,
                "visible_groups": [self.allowed_group.pk],
                "is_pinned": "",
                "_save": "保存",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "只有内部通知才需要选择可查看用户组")
        self.assertFalse(
            Notice.objects.filter(title="范围冲突的联系人通知").exists()
        )

    def test_member_cannot_open_notice_admin(self):
        member = User.objects.create_user(
            username="notice-member",
            password="Member-Password-123!",
        )
        member.must_change_password = False
        member.save(update_fields=["must_change_password"])
        self.client.force_login(member)

        response = self.client.get("/admin/notices/notice/")

        self.assertEqual(response.status_code, 302)


class DirectMessageSendTests(TestCase):
    """写私信：整页表单与页面上的浮动窗共用一个地址，两行一起落，拒绝各归其位。"""

    def setUp(self):
        self.sender = User.objects.create_user(
            username="dm-sender",
            password="Sender-Password-123!",
        )
        self.sender.must_change_password = False
        self.sender.save(update_fields=["must_change_password"])
        self.sender.profile.full_name = "发信人"
        self.sender.profile.save(update_fields=["full_name"])
        self.recipient = User.objects.create_user(
            username="dm-recipient",
            password="Recipient-Password-123!",
        )
        self.recipient.must_change_password = False
        self.recipient.save(update_fields=["must_change_password"])
        self.recipient.profile.full_name = "收信人"
        self.recipient.profile.save(update_fields=["full_name"])
        self.url = reverse(
            "member_notices:direct_compose", args=(self.recipient.pk,)
        )
        self.client.force_login(self.sender)

    def test_compose_page_renders_the_form_with_the_recipient(self):
        response = self.client.get(self.url)

        self.assertContains(response, "写私信")
        self.assertContains(response, "收信人")
        # 上限只有 models.DIRECT_MESSAGE_MAX_CHARS 一处：表单照它拒，widget 照它带 maxlength。
        self.assertContains(response, f'maxlength="{DIRECT_MESSAGE_MAX_CHARS}"')

    def test_sending_writes_the_body_and_the_notification_together(self):
        response = self.client.post(self.url, {"body": "你好，这是一条私信。"}, follow=True)

        self.assertEqual(
            response.redirect_chain,
            [(reverse("member_notices:internal_list"), 302)],
        )
        self.assertContains(response, "私信已发送。")
        direct = DirectMessage.objects.get()
        self.assertEqual(direct.sender, self.sender)
        self.assertEqual(direct.recipient, self.recipient)
        self.assertEqual(direct.body, "你好，这是一条私信。")
        message = Message.objects.get()
        self.assertEqual(message.kind, Message.DIRECT)
        self.assertEqual(message.recipient, self.recipient)
        self.assertEqual(message.actor, self.sender)
        self.assertEqual(message.direct_message, direct)
        self.assertFalse(message.is_read)

    def test_the_window_returns_to_the_page_it_was_opened_from(self):
        # 浮动窗那一份表单把 next 藏在表单里（见 includes/direct_compose.html），
        # 整页那一份把 next 带在地址上；两条路都要回得去。
        profile_url = reverse("accounts:member_profile", args=(self.recipient.pk,))

        from_page = self.client.post(f"{self.url}?next={profile_url}", {"body": "从资料页。"})
        from_window = self.client.post(self.url, {"body": "从窗口。", "next": profile_url})

        self.assertRedirects(from_page, profile_url)
        self.assertRedirects(from_window, profile_url)

    def test_offsite_next_is_ignored(self):
        response = self.client.post(
            self.url,
            {"body": "想跳外站。", "next": "https://evil.example/"},
        )

        self.assertRedirects(
            response,
            reverse("member_notices:internal_list"),
            fetch_redirect_response=False,
        )

    def test_over_long_body_is_rejected_and_the_typed_text_stays(self):
        too_long = "长" * (DIRECT_MESSAGE_MAX_CHARS + 1)

        response = self.client.post(self.url, {"body": too_long})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, too_long)
        self.assertFalse(DirectMessage.objects.exists())
        self.assertFalse(Message.objects.exists())

    def test_blank_body_is_rejected(self):
        response = self.client.post(self.url, {"body": "   "})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "请输入私信内容。")
        self.assertFalse(DirectMessage.objects.exists())

    def test_cannot_send_to_yourself(self):
        response = self.client.post(
            reverse("member_notices:direct_compose", args=(self.sender.pk,)),
            {"body": "给自己发一条。"},
            follow=True,
        )

        self.assertContains(response, "不能给自己发私信。")
        self.assertFalse(DirectMessage.objects.exists())
        self.assertFalse(Message.objects.exists())

    def test_inactive_member_cannot_receive(self):
        self.recipient.is_active = False
        self.recipient.save(update_fields=["is_active"])

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)

    def test_anonymous_is_sent_to_the_login_page(self):
        self.client.logout()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])


class DirectMessageInboxTests(TestCase):
    """收件人那一侧：行读什么、未读怎么算、读完还在、自己删、快速回信。"""

    def setUp(self):
        self.sender = User.objects.create_user(
            username="inbox-sender",
            password="Sender-Password-123!",
        )
        self.sender.must_change_password = False
        self.sender.save(update_fields=["must_change_password"])
        self.sender.profile.full_name = "发信人"
        self.sender.profile.save(update_fields=["full_name"])
        self.recipient = User.objects.create_user(
            username="inbox-recipient",
            password="Recipient-Password-123!",
        )
        self.recipient.must_change_password = False
        self.recipient.save(update_fields=["must_change_password"])
        self.body = "你好，这是一条私信。"
        self.message = send_direct_message(
            sender=self.sender,
            recipient=self.recipient,
            body=self.body,
        )
        self.client.force_login(self.recipient)

    def test_row_reads_type_actor_and_the_body_excerpt(self):
        row = next(
            row for row in message_rows(self.recipient) if row.type_label == "私信"
        )

        self.assertEqual(row.title, "向你发送了一条私信")
        self.assertEqual(row.actor, "发信人")
        self.assertEqual(row.context, self.body)
        self.assertFalse(row.is_read)
        self.assertEqual(row.reply_to_id, self.sender.pk)
        self.assertEqual(
            row.url,
            reverse("member_notices:message_go", args=(self.message.pk,)),
        )

    def test_the_sender_has_no_row_of_their_own(self):
        self.assertEqual(message_rows(self.sender), ())

    def test_the_notification_lights_up_the_badge_and_the_member_home_reminder(self):
        self.assertEqual(unread_message_count(self.recipient), 1)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertContains(response, "1 条未读消息")
        self.assertContains(response, '<span class="entry-badge">1</span>')

    def test_opening_the_row_shows_the_full_text_and_marks_it_read(self):
        response = self.client.get(
            reverse("member_notices:message_go", args=(self.message.pk,))
        )

        self.assertRedirects(
            response,
            reverse("member_notices:direct_detail", args=(self.message.pk,)),
        )
        page = self.client.get(
            reverse("member_notices:direct_detail", args=(self.message.pk,))
        )
        self.assertContains(page, self.body)
        self.message.refresh_from_db()
        self.assertTrue(self.message.is_read)
        self.assertEqual(unread_message_count(self.recipient), 0)

    def test_the_detail_page_shows_the_whole_body_not_the_excerpt(self):
        long_body = "很长的正文。" * 30
        message = send_direct_message(
            sender=self.sender,
            recipient=self.recipient,
            body=long_body,
        )

        page = self.client.get(
            reverse("member_notices:direct_detail", args=(message.pk,))
        )

        self.assertContains(page, long_body)

    def test_reading_keeps_the_message(self):
        mark_message_read(message=self.message)

        page = self.client.get(
            reverse("member_notices:direct_detail", args=(self.message.pk,))
        )

        self.assertEqual(page.status_code, 200)
        self.assertEqual(len(message_rows(self.recipient)), 1)

    def test_delete_removes_the_row_and_the_body(self):
        response = self.client.post(
            reverse("member_notices:direct_delete", args=(self.message.pk,)),
            follow=True,
        )

        self.assertContains(response, "私信已删除。")
        self.assertFalse(Message.objects.filter(pk=self.message.pk).exists())
        self.assertFalse(DirectMessage.objects.exists())
        self.assertEqual(message_rows(self.recipient), ())

    def test_delete_is_post_only(self):
        response = self.client.get(
            reverse("member_notices:direct_delete", args=(self.message.pk,))
        )

        self.assertEqual(response.status_code, 405)

    def test_someone_elses_message_is_not_reachable(self):
        outsider = User.objects.create_user(
            username="inbox-outsider",
            password="Outsider-Password-123!",
        )
        outsider.must_change_password = False
        outsider.save(update_fields=["must_change_password"])
        self.client.force_login(outsider)

        detail = self.client.get(
            reverse("member_notices:direct_detail", args=(self.message.pk,))
        )
        delete = self.client.post(
            reverse("member_notices:direct_delete", args=(self.message.pk,))
        )

        self.assertEqual(detail.status_code, 404)
        self.assertEqual(delete.status_code, 404)
        self.assertTrue(DirectMessage.objects.exists())

    def test_a_non_direct_message_has_no_direct_page(self):
        # 绕过写入函数造一条别的 kind（表上没有组合约束，见模型 docstring）。
        other = Message.objects.create(
            recipient=self.recipient,
            kind=Message.COMMENT,
        )

        response = self.client.get(
            reverse("member_notices:direct_detail", args=(other.pk,))
        )

        self.assertEqual(response.status_code, 404)

    def test_a_direct_row_without_a_body_is_skipped_not_a_500(self):
        broken = Message.objects.create(
            recipient=self.recipient,
            kind=Message.DIRECT,
        )

        page = self.client.get(reverse("member_notices:internal_list"))
        rows = message_rows(self.recipient)

        self.assertEqual(page.status_code, 200)
        self.assertEqual(len(rows), 1)
        # 计数与列表同一个口径：显示不出来的行不能只从列表里消失、却还算在未读里。
        self.assertEqual(unread_message_count(self.recipient), 1)
        self.assertEqual(
            self.client.get(
                reverse("member_notices:message_go", args=(broken.pk,))
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                reverse("member_notices:direct_detail", args=(broken.pk,))
            ).status_code,
            404,
        )

    def test_quick_reply_is_an_ordinary_direct_message_back(self):
        page = self.client.get(reverse("member_notices:internal_list"))

        self.assertContains(page, "快速回信")
        self.assertContains(
            page,
            reverse("member_notices:direct_compose", args=(self.sender.pk,)),
        )

        self.client.post(
            reverse("member_notices:direct_compose", args=(self.sender.pk,)),
            {"body": "收到，回你一条。"},
        )

        reply = Message.objects.get(recipient=self.sender)
        self.assertEqual(reply.kind, Message.DIRECT)
        self.assertEqual(reply.direct_message.sender, self.recipient)
        self.assertEqual(reply.direct_message.body, "收到，回你一条。")
        self.assertEqual(unread_message_count(self.sender), 1)

    def test_rows_without_a_reply_target_do_not_carry_the_button(self):
        # 发信人注销（硬删）后「来自」为空，也就没有可回的人（外键 SET_NULL）。
        self.sender.delete()

        response = self.client.get(reverse("member_notices:internal_list"))

        self.assertNotContains(response, "快速回信")
        self.assertContains(response, self.body)

    def test_a_deactivated_sender_leaves_no_reply_entry(self):
        # 停用才是本平台真正的账号退场口径（有审计行的账号删不掉）。写私信那道门认的是
        # 「收信人在册」，所以这里也得认「发信人在册」——否则按钮点下去是 404，
        # 浮动窗那条路还会把写好的回信弄丢。
        self.sender.is_active = False
        self.sender.save(update_fields=["is_active"])

        row = next(
            row for row in message_rows(self.recipient) if row.type_label == "私信"
        )
        page = self.client.get(reverse("member_notices:internal_list"))
        detail = self.client.get(
            reverse("member_notices:direct_detail", args=(self.message.pk,))
        )

        self.assertIsNone(row.reply_to_id)
        self.assertNotContains(page, "快速回信")
        self.assertEqual(detail.status_code, 200)
        self.assertNotContains(detail, "data-direct-compose")
        # 私信本身照旧看得见：停用的是账号，不是他发过的话。
        self.assertContains(detail, self.body)

    def test_the_entry_hands_the_form_the_page_it_came_from(self):
        # 没有脚本时入口就是一条普通链接：来处带在地址上，发完与「取消」才回得到这一页。
        response = self.client.get(reverse("member_notices:internal_list"))

        self.assertContains(
            response,
            f"?next={quote(reverse('member_notices:internal_list'))}",
        )


class DirectMessageEntryAcceptanceTests(TestCase):
    """入口：成员资料页上对别人有「私信」，对自己没有。"""

    def setUp(self):
        self.viewer = User.objects.create_user(
            username="entry-viewer",
            password="Viewer-Password-123!",
        )
        self.viewer.must_change_password = False
        self.viewer.save(update_fields=["must_change_password"])
        self.other = User.objects.create_user(
            username="entry-other",
            password="Other-Password-123!",
        )
        self.other.must_change_password = False
        self.other.save(update_fields=["must_change_password"])
        self.other.profile.full_name = "被看的成员"
        self.other.profile.save(update_fields=["full_name"])
        self.client.force_login(self.viewer)

    def test_profile_page_offers_the_button_and_the_window_for_another_member(self):
        response = self.client.get(
            reverse("accounts:member_profile", args=(self.other.pk,))
        )

        self.assertContains(
            response,
            reverse("member_notices:direct_compose", args=(self.other.pk,)),
        )
        # 脚本靠这两个属性打开窗口：入口自己带 data-direct-compose，
        # 窗口本体带 data-direct-dialog（见 static/js/direct_compose.js）。
        self.assertContains(response, "data-direct-compose")
        self.assertContains(response, "data-direct-dialog")
        self.assertContains(response, 'data-direct-name="被看的成员"')
        # 没有脚本时它是一条普通链接：来处带着，发完与「取消」回得到资料页。
        self.assertContains(
            response,
            f"?next={quote(reverse('accounts:member_profile', args=(self.other.pk,)))}",
        )

    def test_your_own_profile_page_has_no_direct_entry(self):
        response = self.client.get(
            reverse("accounts:member_profile", args=(self.viewer.pk,))
        )

        self.assertNotContains(
            response,
            reverse("member_notices:direct_compose", args=(self.viewer.pk,)),
        )
        self.assertNotContains(response, "data-direct-dialog")


class DirectMessageAdminAcceptanceTests(TestCase):
    """后台的私信是一张只读表：查得到（按人、按时间、按正文），改不了、删不掉、加不出来。"""

    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username="dm-admin",
            password="Admin-Password-123!",
        )
        self.sender = User.objects.create_user(
            username="dm-admin-sender",
            password="Sender-Password-123!",
        )
        self.sender.profile.full_name = "发信人"
        self.sender.profile.save(update_fields=["full_name"])
        self.recipient = User.objects.create_user(
            username="dm-admin-recipient",
            password="Recipient-Password-123!",
        )
        self.recipient.profile.full_name = "收信人"
        self.recipient.profile.save(update_fields=["full_name"])
        self.body = "后台要看得到的那条私信正文。"
        self.message = send_direct_message(
            sender=self.sender,
            recipient=self.recipient,
            body=self.body,
        )
        self.direct = self.message.direct_message
        self.changelist = reverse("admin:notices_directmessage_changelist")
        self.change = reverse(
            "admin:notices_directmessage_change", args=(self.direct.pk,)
        )
        self.client.force_login(self.superuser)

    def _staff(self, username):
        staff = User.objects.create_user(
            username=username,
            password="Staff-Password-123!",
            is_staff=True,
        )
        staff.must_change_password = False
        staff.save(update_fields=["must_change_password"])
        return staff

    def test_changelist_lists_the_message_with_both_sides(self):
        response = self.client.get(self.changelist)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "发信人")
        self.assertContains(response, "收信人")
        self.assertContains(response, self.body)

    def test_detail_shows_the_whole_body_but_offers_no_editable_field(self):
        response = self.client.get(self.change)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.body)
        # 只读展示（div.readonly），不是可以下笔的控件。
        self.assertNotContains(response, "<textarea")

    def test_a_change_is_refused_and_nothing_is_written(self):
        response = self.client.post(
            self.change,
            {
                "sender": self.sender.pk,
                "recipient": self.recipient.pk,
                "body": "改过的正文",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.direct.refresh_from_db()
        self.assertEqual(self.direct.body, self.body)

    def test_cannot_add_and_cannot_delete(self):
        add = self.client.get(reverse("admin:notices_directmessage_add"))
        delete = self.client.post(
            reverse("admin:notices_directmessage_delete", args=(self.direct.pk,))
        )

        self.assertEqual(add.status_code, 403)
        self.assertEqual(delete.status_code, 403)
        self.assertTrue(DirectMessage.objects.filter(pk=self.direct.pk).exists())

    def test_the_changelist_offers_no_bulk_delete(self):
        response = self.client.get(self.changelist)

        self.assertNotContains(response, "delete_selected")

    def test_staff_without_the_view_permission_cannot_open_it(self):
        self.client.force_login(self._staff("dm-admin-staff"))

        response = self.client.get(self.changelist)

        self.assertEqual(response.status_code, 403)

    def test_staff_granted_the_view_permission_can_read_but_not_write(self):
        staff = self._staff("dm-admin-reader")
        staff.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="notices",
                codename="view_directmessage",
            )
        )
        self.client.force_login(staff)

        detail = self.client.get(self.change)
        write = self.client.post(self.change, {"body": "改过的正文"})

        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, self.body)
        self.assertEqual(write.status_code, 403)

    def test_reading_in_the_backend_writes_no_audit_row(self):
        self.client.get(self.changelist)
        self.client.get(self.change)

        self.assertEqual(AuditLog.objects.count(), 0)
