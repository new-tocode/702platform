"""评审人看到的页面：评审队列、项目组详情，以及页面上的提交表单。

这些用例多数从 HTTP 层走一遍（测试客户端 + 模板），因为要守的是「谁能看到什么」
与「模板渲染得出来」——服务层的规则在别的模块里断言，评审回复与归档的下载入口
归 test_verdicts.py。
"""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from projects.services import apply_to_create_group

from ..models import (
    ReviewTask,
    ProjectSubmission,
    preliminary_task_of,
)
from ..services import override_review, submit_verdict
from .base import (
    TWO_REVIEWER_TYPE,
    ReviewTestCase,
)
from .factories import (
    make_admin,
    make_group,
    make_preliminary_reviewer,
    make_reviewer,
    make_super_reviewer,
    make_user,
    materials_upload,
)


class ReviewPagesTests(ReviewTestCase):
    def setUp(self):
        self.contact = make_user("review-contact")
        self.member = make_user("review-member")
        self.reviewer_one = make_reviewer("reviewer-one")
        self.reviewer_two = make_reviewer("reviewer-two")
        self.preliminary = make_preliminary_reviewer("preliminary-one")
        self.outsider = make_user("review-outsider")
        self.group = make_group("评审项目组", leader=self.contact, members=[self.member])

    # --- queue and detail views ---------------------------------------------

    def test_non_reviewer_cannot_open_review_queue(self):
        self.client.force_login(self.member)

        response = self.client.get(reverse("reviews:queue"))

        self.assertEqual(response.status_code, 403)

    def test_reviewer_sees_assigned_submission_and_can_enter_group_detail(self):
        submission = self._submit()
        self.client.force_login(self.reviewer_one)

        queue_response = self.client.get(reverse("reviews:queue"))
        detail_response = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )

        self.assertEqual(queue_response.status_code, 200)
        self.assertContains(queue_response, self.group.name)
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.context["my_assignment"].submission_id, submission.pk)

    def test_group_detail_is_hidden_from_unrelated_member(self):
        self._submit()
        self.client.force_login(self.outsider)

        response = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )

        self.assertEqual(response.status_code, 403)

    def test_group_member_can_view_review_history(self):
        submission = self._submit()
        submit_verdict(
            task=self._assignment(submission, self.reviewer_one),
            reviewer=self.reviewer_one,
            decision=ReviewTask.APPROVE,
            comment="同意。",
        )
        self.client.force_login(self.member)

        response = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "同意。")

    def test_reviewer_identity_is_hidden_on_group_detail(self):
        submission = self._submit()
        submit_verdict(
            task=self._assignment(submission, self.reviewer_one),
            reviewer=self.reviewer_one,
            decision=ReviewTask.APPROVE,
            comment="同意。",
        )
        self.client.force_login(self.member)

        response = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )

        self.assertContains(response, "评审人 1")
        self.assertContains(response, "初审")
        self.assertNotContains(response, "reviewer-one")
        self.assertNotContains(response, "reviewer-two")
        # 初审人同样匿名：页面上只写「初审」，不写账号。
        self.assertNotContains(response, "preliminary-one")

    def test_the_roster_shows_the_preliminary_line_exactly_once(self):
        """名册里初审只占一行，评审人编号只数评审任务。

        合并成一张任务表后这两件事很容易写坏：直接遍历 ``submission.tasks`` 会把
        初审那条也当成评审人，于是初审出现两行、编号从 2 开始。
        """
        self._submit()
        self.client.force_login(self.member)

        response = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )

        html = response.content.decode()
        self.assertEqual(html.count("<dt>初审</dt>"), 1)
        self.assertIn("<dt>评审人 1</dt>", html)
        self.assertIn("<dt>评审人 2</dt>", html)
        self.assertNotIn("<dt>评审人 3</dt>", html)

    def test_review_form_posts_multipart(self):
        """A browser only sends the reply archive if the form is multipart.

        The test client encodes files as multipart on its own, so without this
        assertion a missing enctype would only ever break in a real browser.
        """
        self._submit()
        self.client.force_login(self.reviewer_one)

        response = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )

        self.assertContains(response, 'enctype="multipart/form-data"')

    def test_contact_submits_and_reviewer_completes_via_views(self):
        """整条链路走视图：提交 → 初审 → 评审。"""
        self.client.force_login(self.contact)
        submit_response = self.client.post(
            reverse("projects:group_submit_review", args=(self.group.pk,)),
            {"review_type": TWO_REVIEWER_TYPE, "message": "申请参加竞赛。"},
        )
        self.assertEqual(submit_response.status_code, 302)

        submission = ProjectSubmission.objects.get(group=self.group)
        self.assertEqual(submission.review_type, TWO_REVIEWER_TYPE)
        self.assertEqual(submission.status, ProjectSubmission.PRELIMINARY_PENDING)

        preliminary = preliminary_task_of(submission)
        self.client.force_login(self.preliminary)
        preliminary_response = self.client.post(
            reverse("reviews:preliminary_complete", args=(preliminary.pk,)),
            {
                "decision": ReviewTask.APPROVE,
                "comment": "同意送审。",
                "reviewers": [self.reviewer_one.pk, self.reviewer_two.pk],
            },
        )
        self.assertEqual(preliminary_response.status_code, 302)
        preliminary.refresh_from_db()
        self.assertEqual(preliminary.status, ReviewTask.COMPLETED)
        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.PENDING)

        assignment = self._assignment(submission, self.reviewer_one)
        self.client.force_login(self.reviewer_one)
        complete_response = self.client.post(
            reverse("reviews:complete", args=(assignment.pk,)),
            {"decision": ReviewTask.APPROVE, "comment": "通过。"},
        )

        self.assertEqual(complete_response.status_code, 302)
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, ReviewTask.COMPLETED)
        self.assertEqual(assignment.decision, ReviewTask.APPROVE)

    def test_group_manage_reports_the_preliminary_stage(self):
        """初审中同样是「本轮未结束」，措辞要说明在等谁。"""
        self._open_round()
        self.client.force_login(self.contact)

        response = self.client.get(
            reverse("projects:group_manage", args=(self.group.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "本轮未结束")
        self.assertContains(response, "初审中")
        self.assertNotContains(
            response, reverse("projects:group_submit_review", args=(self.group.pk,))
        )

    def test_group_manage_hides_the_submit_form_while_a_round_is_open(self):
        self._submit()
        self.client.force_login(self.contact)

        response = self.client.get(
            reverse("projects:group_manage", args=(self.group.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "本轮未结束")
        self.assertNotContains(
            response, reverse("projects:group_submit_review", args=(self.group.pk,))
        )

    def test_group_manage_offers_the_submit_form_when_nothing_is_open(self):
        self.client.force_login(self.contact)

        response = self.client.get(
            reverse("projects:group_manage", args=(self.group.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, reverse("projects:group_submit_review", args=(self.group.pk,))
        )

    def test_reviewer_uploads_reply_file_via_view(self):
        submission = self._submit()
        assignment = self._assignment(submission, self.reviewer_one)
        self.client.force_login(self.reviewer_one)

        response = self.client.post(
            reverse("reviews:complete", args=(assignment.pk,)),
            {
                "decision": ReviewTask.APPROVE,
                "comment": "已在材料上批注。",
                "reply_file": materials_upload("reply.zip"),
            },
        )

        self.assertEqual(response.status_code, 302)
        assignment.refresh_from_db()
        self.assertTrue(assignment.reply_file)
        self.assertTrue(assignment.reply_file.name.endswith(".zip"))

    def test_the_view_refuses_an_empty_comment(self):
        """文字意见是评审的**必需**产出；压缩包才是选填的那一个。

        回复里放的是批注与补充材料，而「通过还是需修改、为什么」必须落在意见里——
        没有意见的评审，项目组拿到的是一个没有理由的结论。
        """
        submission = self._submit()
        assignment = self._assignment(submission, self.reviewer_one)
        self.client.force_login(self.reviewer_one)

        response = self.client.post(
            reverse("reviews:complete", args=(assignment.pk,)),
            {"decision": ReviewTask.APPROVE, "comment": "", "reply_file": materials_upload()},
        )

        self.assertRedirects(
            response, reverse("projects:group_detail", args=(self.group.pk,))
        )
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, ReviewTask.PENDING)
        self.assertFalse(assignment.reply_file)

    def test_materials_upload_rejects_unsupported_extension(self):
        self.client.force_login(self.contact)

        response = self.client.post(
            reverse("projects:group_materials_update", args=(self.group.pk,)),
            {"materials": SimpleUploadedFile("plan.txt", b"hello", content_type="text/plain")},
        )

        self.assertEqual(response.status_code, 302)
        self.group.refresh_from_db()
        self.assertNotEqual(self.group.materials.name, "plan.txt")




class CreateRequestQueueTests(ReviewTestCase):
    """项目组创建申请送到管理员的「评审」页，任一人同意即通过。

    这里的管理员一个评审字段都没开——只要 `is_staff`，队列页与「评审」入口
    就该对他开放（`permissions.can_open_queue`）。
    """

    def setUp(self):
        self.admin = make_admin("queue-admin")
        self.other_admin = make_admin("queue-admin-2")
        self.member = make_user("queue-member")
        self.reviewer = make_reviewer("queue-reviewer")

    def _apply(self, name="嵌入式组"):
        return apply_to_create_group(
            applicant=self.member,
            name=name,
            description="做嵌入式方向的竞赛。",
            college="计算机学院",
            advisor_names=["张三"],
        )

    def test_administrator_without_review_qualification_opens_the_queue(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("reviews:queue"))

        self.assertEqual(response.status_code, 200)

    def test_member_home_shows_the_queue_entry_to_administrators(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertContains(response, reverse("reviews:queue"))

    def test_administrator_sees_the_pending_request_and_decides_it_here(self):
        self._apply()
        self.client.force_login(self.admin)

        response = self.client.get(reverse("reviews:queue"))

        self.assertContains(response, "创建项目组申请")
        self.assertContains(response, "嵌入式组")
        self.assertContains(response, "计算机学院")
        self.assertContains(response, "张三")
        self.assertContains(response, "同意")

    def test_reviewer_without_admin_role_gets_no_create_requests(self):
        self._apply()
        self.client.force_login(self.reviewer)

        response = self.client.get(reverse("reviews:queue"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "嵌入式组")

    def test_first_approval_clears_it_from_the_other_administrators(self):
        create_request = self._apply()
        self.client.force_login(self.admin)
        self.client.post(
            reverse(
                "projects:group_create_decide",
                args=(create_request.pk, "approve"),
            )
        )

        self.client.force_login(self.other_admin)
        response = self.client.get(reverse("reviews:queue"))

        # 待办面板整块消失；上一位管理员那条 flash 消息可能还在会话里，不去管它。
        self.assertNotContains(response, "创建项目组申请")


class ReviewerPickerPageTests(ReviewTestCase):
    """初审人指定评审人的弹窗，以及申请人对初审人的可见性。"""

    def setUp(self):
        self.contact = make_user("picker-contact")
        self.member = make_user("picker-member")
        self.preliminary = make_preliminary_reviewer("picker-preliminary")
        self.reviewer_one = make_reviewer("picker-reviewer-one")
        self.reviewer_two = make_reviewer("picker-reviewer-two")
        self.outsider = make_user("picker-outsider")
        self.group = make_group("指定评审人页面组", leader=self.contact, members=[self.member])

    def _busy_with_another_round(self, reviewer):
        """给评审人挂一条别轮的进行中任务，用来渲染「进行中」状态。"""
        other_group = make_group(
            "另一个项目组", leader=self.outsider, write_materials=False
        )
        other_submission = ProjectSubmission.objects.create(
            group=other_group,
            round=1,
            review_type=TWO_REVIEWER_TYPE,
            submitted_by=self.outsider,
        )
        ReviewTask.objects.create(
            submission=other_submission,
            stage=ReviewTask.REVIEW,
            reviewer=reviewer,
        )

    def test_the_preliminary_reviewer_gets_a_picker_with_names_bios_and_status(self):
        self.preliminary.profile.bio = "熟悉前端与架构。"
        self.preliminary.profile.save(update_fields=["bio"])
        self.reviewer_one.profile.bio = "做过三届省赛。"
        self.reviewer_one.profile.save(update_fields=["bio"])
        self._busy_with_another_round(self.reviewer_two)
        self._open_round()
        self.client.force_login(self.preliminary)

        response = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "指定评审人")
        self.assertContains(response, "做过三届省赛。")
        options = {row["reviewer"].pk: row for row in response.context["reviewer_options"]}
        self.assertFalse(options[self.reviewer_one.pk]["busy"])
        self.assertTrue(options[self.reviewer_two.pk]["busy"])
        self.assertContains(response, "已有进行中的评审任务")
        self.assertContains(response, "空闲")

    def test_the_submitter_sees_the_preliminary_reviewer_and_can_message_them(self):
        self.preliminary.profile.full_name = "初审老师"
        self.preliminary.profile.save(update_fields=["full_name"])
        self._open_round()
        self.client.force_login(self.contact)

        response = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "初审老师")
        self.assertContains(
            response,
            reverse(
                "member_notices:direct_compose", args=(self.preliminary.pk,)
            ),
        )
        self.assertContains(response, "data-direct-compose")
        # 申请人不是初审人，不需要指定评审人。
        self.assertNotIn("reviewer_options", response.context)

    def test_other_group_members_do_not_see_the_preliminary_reviewer(self):
        self.preliminary.profile.full_name = "初审老师"
        self.preliminary.profile.save(update_fields=["full_name"])
        self._open_round()
        self.client.force_login(self.member)

        response = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "初审老师")
        self.assertNotContains(response, "data-direct-compose")

    def test_the_submitter_sees_the_specified_reviewers_names(self):
        """发起人看得到初审人指定了谁；组内其他成员仍然只看到位置编号。"""
        self.reviewer_one.profile.full_name = "评审老师甲"
        self.reviewer_one.profile.save(update_fields=["full_name"])
        self.reviewer_two.profile.full_name = "评审老师乙"
        self.reviewer_two.profile.save(update_fields=["full_name"])
        submission = self._open_round()
        self._pass_preliminary(
            submission, reviewers=[self.reviewer_one, self.reviewer_two]
        )

        self.client.force_login(self.contact)
        submitter_view = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )
        self.assertContains(submitter_view, "评审老师甲")
        self.assertContains(submitter_view, "评审老师乙")
        self.assertContains(submitter_view, "评审人 1")
        # 评审人姓名旁有与初审人同款的私信入口。
        self.assertContains(
            submitter_view,
            reverse(
                "member_notices:direct_compose", args=(self.reviewer_one.pk,)
            ),
        )
        self.assertContains(
            submitter_view,
            reverse(
                "member_notices:direct_compose", args=(self.reviewer_two.pk,)
            ),
        )

        self.client.force_login(self.member)
        member_view = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )
        self.assertNotContains(member_view, "评审老师甲")
        self.assertNotContains(member_view, "评审老师乙")
        self.assertNotContains(
            member_view,
            reverse(
                "member_notices:direct_compose", args=(self.reviewer_one.pk,)
            ),
        )

    def test_the_submitter_still_sees_super_review_anonymously(self):
        """姓名例外只覆盖初审人指定的评审人，不覆盖超级评审那一票。"""
        super_reviewer = make_super_reviewer("picker-super")
        super_reviewer.profile.full_name = "超级老师"
        super_reviewer.profile.save(update_fields=["full_name"])
        submission = self._open_round()
        override_review(
            submission=submission,
            super_reviewer=super_reviewer,
            decision=ReviewTask.APPROVE,
            comment="直接通过。",
        )
        self.client.force_login(self.contact)

        response = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )

        self.assertContains(response, "超级评审")
        self.assertNotContains(response, "超级老师")
