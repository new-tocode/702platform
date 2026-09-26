"""项目组成员名册：一行看出某人在哪些组、各组里是什么身份。"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from ..models import (
    GroupCreateRequest,
    GroupJoinRequest,
    ProjectAdvisor,
    ProjectGroup,
)


User = get_user_model()


class ProjectMemberRosterTests(TestCase):
    """「项目组成员」名册：一行看清某人在哪些组、在各组里是什么身份。

    名册只读——成员认同只能由业务动作产生（入组审批、建组、联系人转让），
    后台不提供分配入口，所以这里也验证新增页不可达。
    """

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin-roster",
            password="Admin-Password-123!",
        )
        self.client.force_login(self.admin)

    def _named(self, username, full_name):
        user = User.objects.create_user(
            username=username,
            password="Initial-Password-123!",
        )
        user.profile.full_name = full_name
        user.profile.save(update_fields=["full_name"])
        return user

    def test_roster_shows_each_group_with_the_identity_held_there(self):
        contact = self._named("roster-contact", "联系人甲")
        member = self._named("roster-member", "成员乙")
        group = ProjectGroup.objects.create(name="名册测试组", leader=contact)
        group.members.add(member)

        response = self.client.get(reverse("admin:projects_projectmember_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "名册测试组（联系人）")
        self.assertContains(response, "名册测试组（成员）")

    def test_people_outside_every_group_stay_off_the_roster(self):
        self._named("roster-nogroup", "没入组的人")

        response = self.client.get(reverse("admin:projects_projectmember_changelist"))

        self.assertNotContains(response, "没入组的人")

    def test_roster_cannot_add_people_directly(self):
        self.assertEqual(
            self.client.get(reverse("admin:projects_projectmember_add")).status_code,
            403,
        )
