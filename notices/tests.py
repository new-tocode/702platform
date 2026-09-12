"""Stage 2 acceptance tests for public and internal notices."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog
from projects.models import ProjectGroup

from .models import Notice


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

    def test_unlocked_member_can_view_internal_notice_but_not_public_route(self):
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
        self.assertNotContains(list_response, self.public_notice.title)
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
