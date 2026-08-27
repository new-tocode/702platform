"""Acceptance tests for competitions and object-level group registration."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from projects.models import ProjectGroup

from .models import Competition, CompetitionRegistration


User = get_user_model()


class CompetitionAcceptanceTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="competition-admin",
            password="Admin-Password-123!",
        )
        self.leader = User.objects.create_user(
            username="competition-leader",
            password="Leader-Password-123!",
        )
        self.leader.must_change_password = False
        self.leader.save(update_fields=["must_change_password"])
        self.member = User.objects.create_user(
            username="competition-member",
            password="Member-Password-123!",
        )
        self.member.must_change_password = False
        self.member.save(update_fields=["must_change_password"])
        self.other_leader = User.objects.create_user(
            username="other-leader",
            password="Other-Leader-123!",
        )
        self.other_leader.must_change_password = False
        self.other_leader.save(update_fields=["must_change_password"])
        self.other_member = User.objects.create_user(
            username="other-member",
            password="Other-Member-123!",
        )
        self.other_member.must_change_password = False
        self.other_member.save(update_fields=["must_change_password"])

        self.group = ProjectGroup.objects.create(
            name="主项目组",
            leader=self.leader,
        )
        self.group.members.add(self.member)
        self.other_group = ProjectGroup.objects.create(
            name="其他项目组",
            leader=self.other_leader,
        )
        self.other_group.members.add(self.other_member)
        self.competition = Competition.objects.create(
            title="全国大学生竞赛",
            description="请项目组按要求准备报名材料。",
            deadline=timezone.now() + timedelta(days=7),
            team_size="2-5 人",
            is_open=True,
            published_by=self.admin,
        )

    def test_leader_can_view_competitions_and_registration_entry(self):
        self.client.force_login(self.leader)

        response = self.client.get(reverse("competitions:list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.competition.title)
        self.assertContains(
            response,
            reverse("competitions:register", args=(self.competition.pk,)),
        )

    def test_leader_can_view_competitions_and_registration_entry(self):
        self.client.force_login(self.leader)

        response = self.client.get(reverse("competitions:list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.competition.title)
        self.assertContains(
            response,
            reverse("competitions:register", args=(self.competition.pk,)),
        )

    def test_competition_entry_is_visible_in_top_navigation_for_leader(self):
        self.client.force_login(self.leader)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/member/competitions/"')
        self.assertContains(response, "竞赛报名")

    def test_competition_entry_is_visible_in_top_navigation_for_admin(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("accounts:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/member/competitions/"')
        self.assertContains(response, "竞赛报名")

    def test_competition_entry_is_hidden_from_regular_member_and_visitor(self):
        member_response = self.client.get(reverse("accounts:home"))
        self.assertNotContains(member_response, "竞赛报名")
        self.assertNotContains(member_response, 'href="/member/competitions/"')

        self.client.force_login(self.member)
        member_response = self.client.get(reverse("accounts:member_home"))
        self.assertNotContains(member_response, "竞赛报名")
        self.assertNotContains(member_response, 'href="/member/competitions/"')

    def test_anonymous_is_redirected_and_regular_member_is_forbidden(self):
        anonymous_response = self.client.get(reverse("competitions:list"))
        self.assertEqual(anonymous_response.status_code, 302)
        self.assertIn(reverse("accounts:login"), anonymous_response["Location"])

        self.client.force_login(self.member)
        member_response = self.client.get(reverse("competitions:list"))
        self.assertEqual(member_response.status_code, 403)

    def test_leader_can_register_own_group_with_group_members(self):
        self.client.force_login(self.leader)

        response = self.client.post(
            reverse("competitions:register", args=(self.competition.pk,)),
            {
                "group": self.group.pk,
                "members": [self.leader.pk, self.member.pk],
                "remark": "按计划参赛。",
            },
        )

        self.assertEqual(response.status_code, 302)
        registration = CompetitionRegistration.objects.get(
            competition=self.competition,
            group=self.group,
        )
        self.assertEqual(registration.registered_by, self.leader)
        self.assertEqual(
            set(registration.members.values_list("pk", flat=True)),
            {self.leader.pk, self.member.pk},
        )

    def test_leader_cannot_register_another_group(self):
        self.client.force_login(self.leader)

        response = self.client.post(
            reverse("competitions:register", args=(self.competition.pk,)),
            {
                "group": self.other_group.pk,
                "members": [self.other_leader.pk, self.other_member.pk],
                "remark": "越权尝试。",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors["group"])
        self.assertFalse(
            CompetitionRegistration.objects.filter(group=self.other_group).exists()
        )

    def test_non_group_member_cannot_be_selected_for_registration(self):
        self.client.force_login(self.leader)

        response = self.client.post(
            reverse("competitions:register", args=(self.competition.pk,)),
            {
                "group": self.group.pk,
                "members": [self.leader.pk, self.other_member.pk],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors["members"])
        self.assertFalse(CompetitionRegistration.objects.exists())

    def test_same_group_cannot_register_twice(self):
        self.client.force_login(self.leader)
        data = {
            "group": self.group.pk,
            "members": [self.leader.pk, self.member.pk],
        }

        first_response = self.client.post(
            reverse("competitions:register", args=(self.competition.pk,)),
            data,
        )
        second_response = self.client.post(
            reverse("competitions:register", args=(self.competition.pk,)),
            data,
        )

        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(second_response.status_code, 200)
        self.assertContains(second_response, "已经登记过这场竞赛")
        self.assertEqual(CompetitionRegistration.objects.count(), 1)

    def test_closed_or_expired_competition_cannot_accept_registration(self):
        self.competition.is_open = False
        self.competition.save(update_fields=["is_open"])
        self.client.force_login(self.leader)

        response = self.client.get(
            reverse("competitions:register", args=(self.competition.pk,))
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("competitions:list"))
        self.assertFalse(CompetitionRegistration.objects.exists())

        self.competition.is_open = True
        self.competition.deadline = timezone.now() - timedelta(minutes=1)
        self.competition.save(update_fields=["is_open", "deadline"])
        response = self.client.post(
            reverse("competitions:register", args=(self.competition.pk,)),
            {
                "group": self.group.pk,
                "members": [self.leader.pk],
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(CompetitionRegistration.objects.exists())

    def test_admin_can_register_any_group(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("competitions:register", args=(self.competition.pk,)),
            {
                "group": self.other_group.pk,
                "members": [self.other_leader.pk, self.other_member.pk],
            },
        )

        self.assertEqual(response.status_code, 302)
        registration = CompetitionRegistration.objects.get(group=self.other_group)
        self.assertEqual(registration.registered_by, self.admin)

    def test_admin_can_publish_competition_and_publisher_is_recorded(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("admin:competitions_competition_add"),
            {
                "title": "校级创新赛",
                "description": "校级赛事说明。",
                "deadline_0": "2030-01-01",
                "deadline_1": "12:00:00",
                "team_size": "3 人",
                "is_open": "on",
                "_save": "保存",
            },
        )

        self.assertEqual(response.status_code, 302)
        competition = Competition.objects.get(title="校级创新赛")
        self.assertEqual(competition.published_by, self.admin)
        self.assertTrue(competition.is_open)

    def test_admin_and_member_project_routes_have_expected_access(self):
        self.client.force_login(self.admin)
        admin_response = self.client.get("/admin/competitions/competition/")
        self.assertEqual(admin_response.status_code, 200)

        self.client.force_login(self.member)
        member_response = self.client.get("/admin/competitions/competition/")
        self.assertEqual(member_response.status_code, 302)
