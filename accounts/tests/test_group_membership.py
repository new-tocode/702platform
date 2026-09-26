"""后台用户组的组内用户：一个穿梭框，能一次加一批、也能一次移一批。

这个「组」是 ``auth.Group``（内部通知的投递范围），成员关系挂在 ``User`` 那一侧，
所以它不是模型字段、走的是 ``services.set_group_members``。
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from core.models import AuditLog
from ..services import set_group_members


User = get_user_model()


class GroupMembershipAdminAcceptanceTests(TestCase):
    """后台「组」页的组内用户：一个穿梭框，能一次加一批、也能一次移一批。

    这个「组」是 ``auth.Group``（内部通知的投递范围），成员关系挂在 ``User``
    那一侧，所以它不是模型字段、走的是 ``services.set_group_members``。
    """

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin-groups",
            password="Admin-Password-123!",
        )
        self.client.force_login(self.admin)
        self.group = Group.objects.create(name="通知投递组")
        self.url = reverse("admin:auth_group_change", args=(self.group.pk,))

    def _member(self, username, full_name=""):
        user = User.objects.create_user(
            username=username,
            password="Initial-Password-123!",
        )
        if full_name:
            user.profile.full_name = full_name
            user.profile.save(update_fields=["full_name"])
        return user

    def _submit(self, members):
        """保存组页表单；``members`` 是整个组应有的成员，没列进去的会被移出。"""
        return self.client.post(
            self.url,
            {
                "name": self.group.name,
                "members": [str(user.pk) for user in members],
                "_save": "保存",
            },
        )

    def _member_ids(self):
        return set(self.group.user_set.values_list("pk", flat=True))

    def test_admin_page_offers_an_editable_member_shuttle(self):
        """「组内用户」得是个能挑人的多选，而不是一段只读文字。"""
        self._member("candidate-in-pool", "候选池里的人")

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="members"')
        self.assertContains(response, 'multiple')
        # 还没有入组的人，也要出现在左侧候选池里——否则无从加起。
        self.assertContains(response, "candidate-in-pool（候选池里的人）")

    def test_admin_can_add_several_users_in_one_save(self):
        first = self._member("bulk-join-one", "甲")
        second = self._member("bulk-join-two", "乙")

        response = self._submit([first, second])

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._member_ids(), {first.pk, second.pk})
        audit = AuditLog.objects.get(action="accounts.group.membership.update")
        self.assertEqual(
            sorted(audit.detail["added"]), ["bulk-join-one", "bulk-join-two"]
        )
        self.assertEqual(audit.detail["removed"], [])

    def test_admin_can_remove_users_and_keep_the_rest(self):
        keeper = self._member("group-keeper", "留下的")
        leaver = self._member("group-leaver", "移出的")
        self.group.user_set.add(keeper, leaver)

        self._submit([keeper])

        self.assertEqual(self._member_ids(), {keeper.pk})
        audit = AuditLog.objects.get(action="accounts.group.membership.update")
        self.assertEqual(audit.detail["added"], [])
        self.assertEqual(audit.detail["removed"], ["group-leaver"])

    def test_saving_the_same_roster_again_changes_nothing(self):
        """重复保存同一份名单不写库、也不留审计行。"""
        member = self._member("group-steady", "没变的人")
        self.group.user_set.add(member)

        self._submit([member])

        self.assertEqual(self._member_ids(), {member.pk})
        self.assertFalse(
            AuditLog.objects.filter(action="accounts.group.membership.update").exists()
        )

    def test_the_whole_roster_can_be_cleared(self):
        member = self._member("group-cleared", "被清掉的人")
        self.group.user_set.add(member)

        self._submit([])

        self.assertEqual(self._member_ids(), set())
        audit = AuditLog.objects.get(action="accounts.group.membership.update")
        self.assertEqual(audit.detail["removed"], ["group-cleared"])

    def test_a_new_group_can_be_created_with_members_already_in_it(self):
        member = self._member("joined-on-create", "建组时就进来")

        response = self.client.post(
            reverse("admin:auth_group_add"),
            {
                "name": "新建就带人的组",
                "members": [str(member.pk)],
                "_save": "保存",
            },
        )

        self.assertEqual(response.status_code, 302)
        created = Group.objects.get(name="新建就带人的组")
        self.assertEqual(
            set(created.user_set.values_list("pk", flat=True)), {member.pk}
        )

    def test_renaming_does_not_disturb_the_roster(self):
        member = self._member("group-renamed", "改名不动人")
        self.group.user_set.add(member)

        self.client.post(
            self.url,
            {
                "name": "改过名的组",
                "members": [str(member.pk)],
                "_save": "保存",
            },
        )

        self.group.refresh_from_db()
        self.assertEqual(self.group.name, "改过名的组")
        self.assertEqual(self._member_ids(), {member.pk})

    def test_service_refuses_a_stale_roster_written_by_two_admins(self):
        """两次保存各写各的现状，最后拼不出谁也没提交过的名单——锁在这一行上。"""
        from ..services import set_group_members

        first = self._member("lock-first", "甲")
        second = self._member("lock-second", "乙")
        set_group_members(
            group=self.group, members=[first], actor=self.admin
        )

        # 第二次保存读到的现状就是第一次写下的：乙进来，甲出去，而不是两份旧名单相加。
        added, removed = set_group_members(
            group=self.group, members=[second], actor=self.admin
        )

        self.assertEqual([user.pk for user in added], [second.pk])
        self.assertEqual([user.pk for user in removed], [first.pk])
        self.assertEqual(self._member_ids(), {second.pk})
