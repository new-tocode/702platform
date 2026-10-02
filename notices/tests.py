"""Stage 2 acceptance tests for public and internal notices."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog
from projects.models import ProjectGroup

from .models import Message, Notice, NoticeRead
from .selectors import message_rows, unread_message_count
from .services import mark_all_read, mark_message_read, mark_read


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
