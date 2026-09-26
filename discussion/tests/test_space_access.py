"""访问与导航：谁能进社团空间、成员目录、板块管理入口。"""

from django.contrib.auth import get_user_model
from django.urls import reverse
from .base import DiscussionViewTestCase


class SpaceAccessViewTests(DiscussionViewTestCase):
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
    def test_navigation_entry_is_member_only_and_highlights_discussion_pages(self):
        space_url = reverse("discussion:space")
        public_home = self.client.get(reverse("accounts:home"))
        self.assertNotContains(public_home, space_url)

        self.client.force_login(self.member)
        member_home = self.client.get(reverse("accounts:home"))
        self.assertContains(member_home, space_url)
        self.assertLess(
            member_home.content.index("公开通知".encode()),
            member_home.content.index("社团空间".encode()),
        )

        space_response = self.client.get(space_url)
        self.assertEqual(space_response.context["nav_section"], "space")
        profile_response = self.client.get(
            reverse("accounts:member_profile", args=(self.other_member.pk,))
        )
        self.assertEqual(profile_response.context["nav_section"], "space")

        locked = self._make_user("discussion-view-locked")
        locked.must_change_password = True
        locked.save(update_fields=["must_change_password"])
        self.client.force_login(locked)
        password_page = self.client.get(reverse("accounts:password_change"))
        self.assertNotContains(password_page, space_url)
    def test_member_can_view_space_and_board_but_not_board_management_controls(self):
        self.client.force_login(self.member)

        space_response = self.client.get(reverse("discussion:space"))
        board_response = self.client.get(
            reverse("discussion:board", args=(self.board.pk,))
        )

        self.assertEqual(space_response.status_code, 200)
        self.assertContains(space_response, "视图测试")
        self.assertContains(space_response, "View Tests")
        self.assertContains(space_response, "板块")
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
