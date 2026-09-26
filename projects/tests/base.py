"""项目组视图测试的共享夹具：管理员、联系人、成员、无组者各一，外加两个项目组。

夹具放这里是有理由的：每个用例都从「这四种人各看到什么」出发，而这个夹具**不决定
任何随机结果**（项目组没有抽签），统一发放不会让断言时灵时不灵。
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from ..models import (
    GroupCreateRequest,
    GroupJoinRequest,
    ProjectAdvisor,
    ProjectGroup,
)


User = get_user_model()


class ProjectViewTestCase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="project-admin",
            password="Admin-Password-123!",
        )
        self.leader = User.objects.create_user(
            username="project-leader",
            password="Leader-Password-123!",
        )
        self.leader.must_change_password = False
        self.leader.save(update_fields=["must_change_password"])
        self.member = User.objects.create_user(
            username="project-member",
            password="Member-Password-123!",
        )
        self.member.must_change_password = False
        self.member.save(update_fields=["must_change_password"])
        self.no_group_user = User.objects.create_user(
            username="project-outsider",
            password="Outsider-Password-123!",
        )
        self.no_group_user.must_change_password = False
        self.no_group_user.save(update_fields=["must_change_password"])
        self.other_leader = User.objects.create_user(
            username="other-leader",
            password="Other-Leader-123!",
        )
        self.other_leader.must_change_password = False
        self.other_leader.save(update_fields=["must_change_password"])

        self.group = ProjectGroup.objects.create(
            name="机器人组",
            leader=self.leader,
            description="负责机器人竞赛。",
        )
        self.group.members.add(self.member)
        self.other_group = ProjectGroup.objects.create(
            name="算法组",
            leader=self.other_leader,
        )
