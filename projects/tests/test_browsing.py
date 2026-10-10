"""列表与详情：谁看得到哪个组、详情页显示什么，以及列表页的搜索与筛选。"""

from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.urls import reverse
from ..models import (
    GroupCreateRequest,
    GroupJoinRequest,
    ProjectAdvisor,
    ProjectGroup,
)
from .base import ProjectViewTestCase


User = get_user_model()


class GroupBrowsingViewTests(ProjectViewTestCase):
    def test_group_leader_is_automatically_a_group_member(self):
        self.assertIn(self.leader, self.group.members.all())
        self.assertIn(self.member, self.group.members.all())
    def test_group_member_sees_only_their_own_group(self):
        self.client.force_login(self.member)

        response = self.client.get(reverse("projects:group_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.group.name)
        self.assertNotContains(response, self.other_group.name)
    def test_user_without_group_sees_all_groups_to_apply(self):
        self.client.force_login(self.no_group_user)

        response = self.client.get(reverse("projects:group_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.group.name)
        self.assertContains(response, self.other_group.name)
        self.assertContains(response, "申请加入")
    def test_contact_sees_all_groups_with_manage_link(self):
        self.client.force_login(self.leader)

        response = self.client.get(reverse("projects:group_list"))

        self.assertContains(response, self.group.name)
        self.assertContains(response, self.other_group.name)
        self.assertContains(
            response,
            reverse("projects:group_manage", args=(self.group.pk,)),
        )
    def test_anonymous_cannot_view_project_groups(self):
        response = self.client.get(reverse("projects:group_list"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])
    def test_group_detail_derives_extension_from_proposal_filename(self):
        self.group.proposal = "project_proposals/2026/09/开题报告.pdf"
        self.group.save(update_fields=["proposal"])
        self.client.force_login(self.leader)

        response = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "开题报告.pdf")
        self.assertContains(response, "PDF")
    def test_group_detail_and_list_show_college_and_advisors(self):
        self.group.college = "计算机学院"
        self.group.save(update_fields=["college"])
        ProjectAdvisor.objects.create(group=self.group, name="张三", sort_order=0)
        ProjectAdvisor.objects.create(group=self.group, name="李四", sort_order=1)
        self.client.force_login(self.leader)

        detail = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "计算机学院")
        self.assertContains(detail, "张三、李四")

        listing = self.client.get(reverse("projects:group_list"))
        self.assertEqual(listing.status_code, 200)
        self.assertContains(listing, "计算机学院")
        self.assertContains(listing, "张三、李四")
    def test_group_without_advisors_renders_placeholder_in_detail(self):
        """没填时详情页仍要渲染得出来，用 — 占位而不是留空。"""
        self.client.force_login(self.leader)

        response = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "项目组信息")
        self.assertContains(response, "指导老师")
        self.assertNotContains(response, ">DOC</span>")


class GroupListSearchTests(ProjectViewTestCase):
    """列表页搜索：一个关键字扫组名与三种姓名，且不越过可见范围。"""

    def setUp(self):
        super().setUp()
        self.leader.profile.full_name = "张三"
        self.leader.profile.save(update_fields=["full_name"])
        self.member.profile.full_name = "李四"
        self.member.profile.save(update_fields=["full_name"])
        ProjectAdvisor.objects.create(group=self.group, name="王老师", sort_order=0)
        self.client.force_login(self.admin)

    def _rows(self, **params):
        response = self.client.get(reverse("projects:group_list"), params)
        self.assertEqual(response.status_code, 200)
        return [row["group"].name for row in response.context["group_rows"]]

    def test_search_by_group_name(self):
        self.assertEqual(self._rows(q="机器人"), ["机器人组"])

    def test_search_by_leader_full_name(self):
        self.assertEqual(self._rows(q="张三"), ["机器人组"])

    def test_search_by_member_full_name(self):
        self.assertEqual(self._rows(q="李四"), ["机器人组"])

    def test_search_by_advisor_name(self):
        self.assertEqual(self._rows(q="王老师"), ["机器人组"])

    def test_search_falls_back_to_username(self):
        """full_name 为空时页面上显示的是 username，搜索也要认它。"""
        self.assertEqual(self._rows(q="other-leader"), ["算法组"])

    def test_search_lists_each_group_once(self):
        """联系人也在成员名单里，两处都命中时不能因 JOIN 把同一组列两遍。"""
        self.assertEqual(self._rows(q="project-leader"), ["机器人组"])

    def test_search_stays_inside_visible_scope(self):
        """成员只在自己可见的组里搜：别的组不上列表，也就搜不出来。"""
        self.client.force_login(self.member)

        self.assertEqual(self._rows(q="机器人"), ["机器人组"])
        self.assertEqual(self._rows(q="算法"), [])

    def test_search_does_not_shrink_the_card_member_count(self):
        """搜到的只是组里一个人时，卡片上的人数仍是**全组**人数。

        数字要与同屏的名单一致：过滤筛的是这个组在不在列表里，不该把组内的人
        也筛掉（`Count("members")` 落在被过滤的那条 join 上就会犯这个错）。
        """
        extra = User.objects.create_user(
            username="search-extra",
            password="Extra-Password-123!",
        )
        extra.profile.full_name = "高飞"
        extra.profile.save(update_fields=["full_name"])
        self.group.members.add(extra)

        response = self.client.get(reverse("projects:group_list"), {"q": "高飞"})

        rows = response.context["group_rows"]
        self.assertEqual([row["group"].name for row in rows], ["机器人组"])
        self.assertEqual(
            rows[0]["group"].member_count,
            len(rows[0]["group"].members.all()),
        )
        self.assertEqual(rows[0]["group"].member_count, 3)

    def test_blank_keyword_returns_everything_visible(self):
        self.assertEqual(set(self._rows(q="   ")), {"机器人组", "算法组"})

    def test_no_match_shows_empty_state(self):
        response = self.client.get(
            reverse("projects:group_list"), {"q": "不存在的组"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["group_rows"], [])
        self.assertContains(response, "没有匹配的项目组。")


class GroupListMineFilterTests(ProjectViewTestCase):
    """「我的项目组」：把自己作为联系人/组员的组收成一张更短的列表。"""

    def _page(self, user, **params):
        self.client.force_login(user)
        response = self.client.get(reverse("projects:group_list"), params)
        self.assertEqual(response.status_code, 200)
        return response, [row["group"].name for row in response.context["group_rows"]]

    def test_contact_sees_only_own_groups(self):
        """联系人平时看得到全部组，切到「我的项目组」后只剩自己参与的那些。"""
        _, names = self._page(self.leader, mine="1")

        self.assertEqual(names, ["机器人组"])

    def test_admin_sees_only_own_groups(self):
        """管理员同理：「我的」问的是我参与的组，不是我能管的全部组。"""
        self.group.members.add(self.admin)

        _, names = self._page(self.admin, mine="1")

        self.assertEqual(names, ["机器人组"])

    def test_user_without_group_sees_hint(self):
        response, names = self._page(self.no_group_user, mine="1")

        self.assertEqual(names, [])
        self.assertContains(response, "你还没有加入任何项目组。")

    def test_filter_combines_with_keyword(self):
        """两个参数各管各的：在「我的」范围里再按关键字收一遍。"""
        _, names = self._page(self.leader, mine="1", q="算法")

        self.assertEqual(names, [])

    def test_search_form_keeps_filter(self):
        """提交搜索时 mine 要跟着走，否则搜一次筛选就被打回全部。"""
        response, _ = self._page(self.leader, mine="1")

        self.assertContains(response, 'name="mine" value="1"')

    def test_toggle_link_keeps_keyword(self):
        """从「我的项目组」切回全部时，搜索框里的词不该被丢掉。"""
        response, _ = self._page(self.leader, mine="1", q="机器人")

        self.assertContains(response, 'href="?%s"' % urlencode({"q": "机器人"}))

    def test_clear_link_keeps_filter(self):
        """「清除」只清搜索词，不顺手把「我的项目组」也关掉。"""
        response, _ = self._page(self.leader, mine="1", q="机器人")

        self.assertContains(response, 'href="?mine=1"')
