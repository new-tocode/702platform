"""项目组详情页上的「竞赛报名」区块：本组报了哪几场竞赛。

口径由 ``competitions.panels.group_detail_context`` 定：报名记录没有状态字段，放弃即
删除，所以列出来的就是「当前报名」的那几场；已截止的竞赛仍留在表里，只换状态。
可见范围等于 «能打开这个详情页» 本身（成员、管理员、评审人），不再加一道。
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from competitions.models import Competition, CompetitionRegistration
from reviews.models import (
    REVIEW_TYPE_COMPETITION_PROJECT,
    ProjectSubmission,
    ReviewTask,
)

from .base import ProjectViewTestCase


User = get_user_model()


class GroupCompetitionPanelTests(ProjectViewTestCase):
    def setUp(self):
        super().setUp()
        self.open_competition = Competition.objects.create(
            title="全国大学生机器人大赛",
            description="校内选拔另行通知。",
            deadline=timezone.now() + timedelta(days=7),
            is_open=True,
            published_by=self.admin,
        )
        self.expired_competition = Competition.objects.create(
            title="已经截止的创新赛",
            description="",
            deadline=timezone.now() - timedelta(days=1),
            is_open=True,
            published_by=self.admin,
        )

    def _register(self, competition, group, leader):
        registration = CompetitionRegistration.objects.create(
            competition=competition,
            group=group,
            registered_by=leader,
            team_leader=leader,
        )
        registration.members.set(group.members.all())
        return registration

    def _detail(self, group):
        return self.client.get(reverse("projects:group_detail", args=(group.pk,)))

    def test_detail_lists_the_competitions_this_group_registered_for(self):
        self._register(self.open_competition, self.group, self.leader)
        self.client.force_login(self.member)

        response = self._detail(self.group)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.open_competition.title)
        self.assertContains(response, "报名开放中")

    def test_detail_still_lists_a_competition_the_group_can_no_longer_join(self):
        """截止不会让报名记录消失，页面上照列，只把状态换成「已截止」。"""
        self._register(self.expired_competition, self.group, self.leader)
        self.client.force_login(self.leader)

        response = self._detail(self.group)

        self.assertContains(response, self.expired_competition.title)
        self.assertContains(response, "报名已截止")

    def test_detail_shows_only_this_groups_registrations(self):
        """别组的报名不上这一页——否则「本项目组报了哪些」就无从读起。"""
        self._register(self.open_competition, self.other_group, self.other_leader)
        self.client.force_login(self.member)

        response = self._detail(self.group)

        self.assertContains(response, "该项目组尚未报名任何竞赛。")
        self.assertNotContains(response, self.open_competition.title)

    def test_detail_of_a_group_that_registered_nothing_says_so(self):
        self.client.force_login(self.admin)

        response = self._detail(self.group)

        self.assertContains(response, "竞赛报名")
        self.assertContains(response, "该项目组尚未报名任何竞赛。")

    def test_a_reviewer_holding_a_task_sees_the_panel_too(self):
        """区块不另判可见性：门槛就是 can_view_group，评审人凭任务进来也看得到。

        这正是「报名＋成员名单本来就公开」的含义；哪天有人在面板上另加一道
        「是不是组员」的条件，这条会红。
        """
        self._register(self.open_competition, self.group, self.leader)
        reviewer = User.objects.create_user(
            username="competition-panel-reviewer",
            password="Reviewer-Password-123!",
        )
        reviewer.must_change_password = False
        reviewer.save(update_fields=["must_change_password"])
        submission = ProjectSubmission.objects.create(
            group=self.group,
            review_type=REVIEW_TYPE_COMPETITION_PROJECT,
            submitted_by=self.leader,
        )
        ReviewTask.objects.create(
            submission=submission,
            stage=ReviewTask.PRELIMINARY,
            reviewer=reviewer,
        )
        self.client.force_login(reviewer)

        response = self._detail(self.group)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.open_competition.title)
