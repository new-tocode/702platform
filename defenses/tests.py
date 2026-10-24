"""线下模拟答辩的验收测试。

一个主题一组用例：发起与通知、排期列表、评论、修改留痕、关闭只读。
夹具保持「每种身份一个账号」，具体的人留在各组的 ``setUp`` 里。
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from notices.models import Message
from notices.selectors import message_rows
from projects.models import ProjectGroup

from .models import DefenseComment, DefenseRequest
from .services import add_comment, close_request, create_request, update_request


User = get_user_model()


class DefenseTestBase(TestCase):
    """一个项目组，以及每种相关身份各一个账号。"""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="defense-admin",
            password="Admin-Password-123!",
        )
        self.contact = self._user("defense-contact")
        self.other_contact = self._user("defense-other-contact")
        self.member = self._user("defense-member")
        self.reviewer = self._user("defense-reviewer")
        self.preliminary = self._user("defense-preliminary")
        self.super_reviewer = self._user("defense-super")
        self.outsider = self._user("defense-outsider")
        self.reviewer.is_reviewer = True
        self.reviewer.save(update_fields=["is_reviewer"])
        self.preliminary.is_preliminary_reviewer = True
        self.preliminary.save(update_fields=["is_preliminary_reviewer"])
        self.super_reviewer.is_super_reviewer = True
        self.super_reviewer.save(update_fields=["is_super_reviewer"])

        self.group = ProjectGroup.objects.create(
            name="机器人组",
            leader=self.contact,
        )
        self.group.members.add(self.member)
        self.other_group = ProjectGroup.objects.create(
            name="算法组",
            leader=self.other_contact,
        )

    def _user(self, username):
        user = User.objects.create_user(
            username=username,
            password="Member-Password-123!",
        )
        user.must_change_password = False
        user.save(update_fields=["must_change_password"])
        return user

    def _login(self, user):
        self.client.force_login(user)

    def _request(self, *, applicant=None, group=None, content="10 月 30 日 19:00，地点：实验楼 302。", **kwargs):
        return DefenseRequest.objects.create(
            group=group or self.group,
            applicant=applicant or self.contact,
            content=content,
            **kwargs,
        )

    def _comment(self, defense_request, *, author=None, body="时间可以，地点需要改到 305。", kind=DefenseComment.COMMENT):
        return DefenseComment.objects.create(
            request=defense_request,
            author=author or self.reviewer,
            kind=kind,
            body=body,
        )


class DefenseRequestCreateTests(DefenseTestBase):
    """发起入口在项目组管理页；能管这个组的人才能发起。"""

    def test_group_manage_page_shows_the_entry_and_existing_requests(self):
        existing = self._request()
        self._login(self.contact)

        response = self.client.get(
            reverse("projects:group_manage", args=(self.group.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "申请线下模拟答辩")
        self.assertContains(
            response,
            reverse("defenses:request_create", args=(self.group.pk,)),
        )
        self.assertContains(response, reverse("defenses:detail", args=(existing.pk,)))

    def test_contact_can_open_the_form_and_see_the_time_and_place_hint(self):
        self._login(self.contact)

        response = self.client.get(
            reverse("defenses:request_create", args=(self.group.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "请写明答辩的时间和地点")
        self.assertContains(response, 'maxlength="500"')

    def test_contact_can_create_a_request_and_is_taken_to_the_detail(self):
        self._login(self.contact)

        response = self.client.post(
            reverse("defenses:request_create", args=(self.group.pk,)),
            {"content": "  10 月 30 日 19:00，实验楼 302  "},
        )

        created = DefenseRequest.objects.get()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            reverse("defenses:detail", args=(created.pk,)),
        )
        self.assertEqual(created.group, self.group)
        self.assertEqual(created.applicant, self.contact)
        self.assertEqual(created.content, "10 月 30 日 19:00，实验楼 302")
        self.assertEqual(created.status, DefenseRequest.OPEN)

    def test_admin_can_create_for_any_group(self):
        self._login(self.admin)

        response = self.client.post(
            reverse("defenses:request_create", args=(self.other_group.pk,)),
            {"content": "11 月 1 日 14:00，地点：实验楼 105。"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            DefenseRequest.objects.filter(
                group=self.other_group,
                applicant=self.admin,
            ).exists()
        )

    def test_ordinary_member_and_other_contact_are_denied(self):
        url = reverse("defenses:request_create", args=(self.group.pk,))

        for user in (self.member, self.other_contact, self.reviewer):
            with self.subTest(user=user.username):
                self._login(user)
                response = self.client.post(url, {"content": "想申请。"})
                self.assertEqual(response.status_code, 403)
        self.assertFalse(DefenseRequest.objects.exists())

    def test_overlong_content_is_rejected_and_nothing_is_created(self):
        self._login(self.contact)

        response = self.client.post(
            reverse("defenses:request_create", args=(self.group.pk,)),
            {"content": "字" * 501},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(DefenseRequest.objects.exists())
        self.assertTrue(response.context["form"].errors.get("content"))

    def test_blank_content_is_rejected(self):
        self._login(self.contact)

        self.client.post(
            reverse("defenses:request_create", args=(self.group.pk,)),
            {"content": "   "},
        )

        self.assertFalse(DefenseRequest.objects.exists())


class DefenseNotificationTests(DefenseTestBase):
    """创建时给三类评审资格各一条消息，并能从「我的消息」点进详情。"""

    def test_every_qualification_holder_gets_exactly_one_message(self):
        self.reviewer.is_preliminary_reviewer = True
        self.reviewer.is_super_reviewer = True
        self.reviewer.save(
            update_fields=[
                "is_preliminary_reviewer",
                "is_super_reviewer",
            ]
        )
        self._login(self.contact)

        self.client.post(
            reverse("defenses:request_create", args=(self.group.pk,)),
            {"content": "10 月 30 日 19:00，实验楼 302。"},
        )

        created = DefenseRequest.objects.get()
        recipients = set(
            Message.objects.filter(kind=Message.DEFENSE_REQUEST).values_list(
                "recipient_id", flat=True
            )
        )
        self.assertEqual(
            recipients,
            {self.reviewer.pk, self.preliminary.pk, self.super_reviewer.pk},
        )
        self.assertEqual(
            Message.objects.filter(
                kind=Message.DEFENSE_REQUEST,
                recipient=self.reviewer,
            ).count(),
            1,
        )
        self.assertFalse(
            Message.objects.filter(
                kind=Message.DEFENSE_REQUEST,
                recipient=self.outsider,
            ).exists()
        )
        self.assertFalse(
            Message.objects.filter(
                kind=Message.DEFENSE_REQUEST,
                recipient=self.admin,
            ).exists()
        )

    def test_message_row_links_to_the_detail_and_shows_the_live_status(self):
        defense_request = create_request(
            group=self.group,
            applicant=self.contact,
            content="10 月 30 日 19:00，实验楼 302。",
        )
        message = Message.objects.get(
            kind=Message.DEFENSE_REQUEST,
            recipient=self.reviewer,
        )

        row = next(
            row for row in message_rows(self.reviewer)
            if row.type_label == "线下答辩"
        )
        self.assertIn(self.group.name, row.title)
        self.assertEqual(row.context, "安排中")
        self.assertEqual(
            row.url,
            reverse("member_notices:message_go", args=(message.pk,)),
        )

        self._login(self.reviewer)
        response = self.client.get(row.url)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            reverse("defenses:detail", args=(defense_request.pk,)),
        )
        message.refresh_from_db()
        self.assertTrue(message.is_read)

    def test_message_context_follows_the_request_into_closed(self):
        defense_request = create_request(
            group=self.group,
            applicant=self.contact,
            content="10 月 30 日 19:00，实验楼 302。",
        )
        close_request(defense_request=defense_request, actor=self.contact)

        row = next(
            row for row in message_rows(self.reviewer)
            if row.type_label == "线下答辩"
        )

        self.assertEqual(row.context, "已确定")

    def test_a_defense_message_without_its_source_is_skipped(self):
        Message.objects.create(
            recipient=self.reviewer,
            actor=self.contact,
            kind=Message.DEFENSE_REQUEST,
        )

        self.assertEqual(message_rows(self.reviewer), ())
        self._login(self.reviewer)
        self.assertEqual(
            self.client.get(reverse("member_notices:internal_list")).status_code,
            200,
        )


class DefenseScheduleTests(DefenseTestBase):
    """两块列表、排序与准入。"""

    def test_reviewers_and_admins_can_open_the_schedule_but_outsiders_cannot(self):
        url = reverse("defenses:schedule")

        for user in (
            self.admin,
            self.reviewer,
            self.preliminary,
            self.super_reviewer,
        ):
            with self.subTest(user=user.username):
                self._login(user)
                self.assertEqual(self.client.get(url).status_code, 200)

        for user in (self.member, self.outsider):
            with self.subTest(user=user.username):
                self._login(user)
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_new_request_is_in_open_and_closing_moves_it_to_closed(self):
        defense_request = self._request()
        self._login(self.reviewer)

        response = self.client.get(reverse("defenses:schedule"))
        self.assertIn(defense_request, list(response.context["open_requests"]))
        self.assertNotIn(defense_request, list(response.context["closed_requests"]))

        close_request(defense_request=defense_request, actor=self.contact)

        response = self.client.get(reverse("defenses:schedule"))
        self.assertNotIn(defense_request, list(response.context["open_requests"]))
        self.assertIn(defense_request, list(response.context["closed_requests"]))

    def test_both_lists_are_ordered_newest_first(self):
        older = self._request(content="旧的一条")
        newer = self._request(content="新的一条")
        now = timezone.now()
        DefenseRequest.objects.filter(pk=older.pk).update(
            created_at=now - timedelta(days=2)
        )
        DefenseRequest.objects.filter(pk=newer.pk).update(
            created_at=now - timedelta(days=1)
        )
        closed_older = self._request(content="旧的已确定", status=DefenseRequest.CLOSED)
        closed_newer = self._request(content="新的已确定", status=DefenseRequest.CLOSED)
        DefenseRequest.objects.filter(pk=closed_older.pk).update(
            created_at=now - timedelta(days=2)
        )
        DefenseRequest.objects.filter(pk=closed_newer.pk).update(
            created_at=now - timedelta(days=1)
        )
        self._login(self.reviewer)

        response = self.client.get(reverse("defenses:schedule"))

        self.assertEqual(
            [item.pk for item in response.context["open_requests"]],
            [newer.pk, older.pk],
        )
        self.assertEqual(
            [item.pk for item in response.context["closed_requests"]],
            [closed_newer.pk, closed_older.pk],
        )

    def test_review_queue_has_the_entry(self):
        self._login(self.reviewer)

        response = self.client.get(reverse("reviews:queue"))

        self.assertContains(response, reverse("defenses:schedule"))
        self.assertContains(response, "线下答辩")


class DefenseCommentTests(DefenseTestBase):
    """评审、管理员与申请人能评论；关闭后不能；别人不能。"""

    def test_reviewer_can_comment_and_lands_on_the_new_comment(self):
        defense_request = self._request()
        self._login(self.reviewer)

        response = self.client.post(
            reverse("defenses:comment_create", args=(defense_request.pk,)),
            {"body": "  时间可以，地点需要改到 305。  "},
        )

        comment = DefenseComment.objects.get()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].endswith(f"#comment-{comment.pk}"))
        self.assertEqual(comment.kind, DefenseComment.COMMENT)
        self.assertEqual(comment.body, "时间可以，地点需要改到 305。")
        self.assertEqual(comment.author, self.reviewer)

    def test_applicant_and_admin_can_also_comment(self):
        defense_request = self._request()

        for user in (self.contact, self.admin):
            with self.subTest(user=user.username):
                self._login(user)
                response = self.client.post(
                    reverse("defenses:comment_create", args=(defense_request.pk,)),
                    {"body": f"{user.username} 的评论"},
                )
                self.assertEqual(response.status_code, 302)
        self.assertEqual(DefenseComment.objects.count(), 2)

    def test_outsider_and_plain_member_cannot_comment(self):
        defense_request = self._request()

        for user in (self.outsider, self.member):
            with self.subTest(user=user.username):
                self._login(user)
                response = self.client.post(
                    reverse("defenses:comment_create", args=(defense_request.pk,)),
                    {"body": "我也想说一句。"},
                )
                self.assertEqual(response.status_code, 403)
        self.assertFalse(DefenseComment.objects.exists())

    def test_blank_comment_is_rejected(self):
        defense_request = self._request()
        self._login(self.reviewer)

        self.client.post(
            reverse("defenses:comment_create", args=(defense_request.pk,)),
            {"body": "   "},
        )

        self.assertFalse(DefenseComment.objects.exists())

    def test_closed_request_rejects_new_comments(self):
        defense_request = self._request(status=DefenseRequest.CLOSED)
        self._login(self.reviewer)

        response = self.client.post(
            reverse("defenses:comment_create", args=(defense_request.pk,)),
            {"body": "还想补一句。"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(DefenseComment.objects.exists())

    def test_closed_detail_shows_history_and_final_text_without_forms(self):
        defense_request = self._request()
        self._comment(defense_request, body="时间需要改。")
        close_request(
            defense_request=defense_request,
            actor=self.contact,
        )
        defense_request.refresh_from_db()
        self._login(self.reviewer)

        response = self.client.get(
            reverse("defenses:detail", args=(defense_request.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "时间需要改。")
        self.assertContains(response, defense_request.content)
        self.assertContains(response, "已确定")
        self.assertIsNone(response.context["comment_form"])
        self.assertFalse(response.context["can_comment"])


class DefenseEditTests(DefenseTestBase):
    """申请人改正文，每次实际变化自动留一条记录。"""

    def test_applicant_edit_updates_text_and_writes_one_edit_comment(self):
        defense_request = self._request()
        self._login(self.contact)

        response = self.client.post(
            reverse("defenses:request_edit", args=(defense_request.pk,)),
            {"content": "改为 10 月 31 日 19:00，地点：实验楼 305。"},
        )

        defense_request.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            defense_request.content,
            "改为 10 月 31 日 19:00，地点：实验楼 305。",
        )
        comment = DefenseComment.objects.get()
        self.assertEqual(comment.kind, DefenseComment.EDIT)
        self.assertEqual(comment.author, self.contact)
        self.assertEqual(comment.body, "")

    def test_edit_comment_is_rendered_as_the_fixed_sentence(self):
        defense_request = self._request()
        update_request(
            defense_request=defense_request,
            content="改到 305。",
            actor=self.contact,
        )
        self._login(self.contact)

        response = self.client.get(
            reverse("defenses:detail", args=(defense_request.pk,))
        )

        self.assertContains(response, "申请者修改了答辩申请")

    def test_identical_edit_does_not_add_a_comment(self):
        defense_request = self._request()
        self._login(self.contact)

        response = self.client.post(
            reverse("defenses:request_edit", args=(defense_request.pk,)),
            {"content": defense_request.content},
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(DefenseComment.objects.exists())

    def test_only_the_applicant_can_edit(self):
        defense_request = self._request()

        for user in (self.reviewer, self.admin, self.other_contact):
            with self.subTest(user=user.username):
                self._login(user)
                response = self.client.post(
                    reverse("defenses:request_edit", args=(defense_request.pk,)),
                    {"content": "别人改的。"},
                )
                self.assertEqual(response.status_code, 403)
        defense_request.refresh_from_db()
        self.assertEqual(defense_request.content, "10 月 30 日 19:00，地点：实验楼 302。")
        self.assertFalse(DefenseComment.objects.exists())

    def test_closed_request_cannot_be_edited(self):
        defense_request = self._request(status=DefenseRequest.CLOSED)
        self._login(self.contact)

        response = self.client.post(
            reverse("defenses:request_edit", args=(defense_request.pk,)),
            {"content": "关闭后再改。"},
        )

        self.assertEqual(response.status_code, 403)
        defense_request.refresh_from_db()
        self.assertEqual(defense_request.content, "10 月 30 日 19:00，地点：实验楼 302。")

    def test_edit_form_only_appears_for_the_applicant_while_open(self):
        defense_request = self._request()

        self._login(self.contact)
        response = self.client.get(
            reverse("defenses:detail", args=(defense_request.pk,))
        )
        self.assertTrue(response.context["can_edit"])
        self.assertContains(
            response,
            reverse("defenses:request_edit", args=(defense_request.pk,)),
        )

        self._login(self.reviewer)
        response = self.client.get(
            reverse("defenses:detail", args=(defense_request.pk,))
        )
        self.assertFalse(response.context["can_edit"])
        self.assertNotContains(
            response,
            reverse("defenses:request_edit", args=(defense_request.pk,)),
        )


class DefenseCloseTests(DefenseTestBase):
    """申请人或管理员关闭；评审不行；关闭后只读。"""

    def test_applicant_closes_and_the_request_becomes_read_only(self):
        defense_request = self._request()
        self._login(self.contact)

        response = self.client.post(
            reverse("defenses:request_close", args=(defense_request.pk,))
        )

        defense_request.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(defense_request.status, DefenseRequest.CLOSED)
        self.assertEqual(defense_request.closed_by, self.contact)
        self.assertIsNotNone(defense_request.closed_at)

    def test_admin_can_close_someone_elses_request(self):
        defense_request = self._request()
        self._login(self.admin)

        response = self.client.post(
            reverse("defenses:request_close", args=(defense_request.pk,))
        )

        defense_request.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(defense_request.status, DefenseRequest.CLOSED)
        self.assertEqual(defense_request.closed_by, self.admin)

    def test_reviewers_cannot_close(self):
        defense_request = self._request()
        self._login(self.reviewer)

        response = self.client.post(
            reverse("defenses:request_close", args=(defense_request.pk,))
        )

        self.assertEqual(response.status_code, 403)
        defense_request.refresh_from_db()
        self.assertEqual(defense_request.status, DefenseRequest.OPEN)

    def test_already_closed_request_cannot_be_closed_again(self):
        defense_request = self._request(status=DefenseRequest.CLOSED)
        self._login(self.contact)

        response = self.client.post(
            reverse("defenses:request_close", args=(defense_request.pk,))
        )

        self.assertEqual(response.status_code, 403)

    def test_detail_after_close_has_no_edit_or_comment_forms(self):
        defense_request = self._request()
        close_request(defense_request=defense_request, actor=self.contact)
        self._login(self.contact)

        response = self.client.get(
            reverse("defenses:detail", args=(defense_request.pk,))
        )

        self.assertIsNone(response.context["edit_form"])
        self.assertIsNone(response.context["comment_form"])
        self.assertFalse(response.context["can_close"])
        self.assertContains(response, "不能再修改或评论")

    def test_forged_service_call_after_close_is_refused(self):
        defense_request = self._request()
        close_request(defense_request=defense_request, actor=self.contact)

        from django.core.exceptions import PermissionDenied

        with self.assertRaises(PermissionDenied):
            add_comment(
                defense_request=defense_request,
                body="绕过视图。",
                actor=self.reviewer,
            )
