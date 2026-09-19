"""评审人看到的页面：评审队列、项目组详情，以及页面上的提交表单。

这些用例多数从 HTTP 层走一遍（测试客户端 + 模板），因为要守的是「谁能看到什么」
与「模板渲染得出来」——服务层的规则在别的模块里断言，批注版与归档的下载入口
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
from ..services import submit_verdict
from .base import (
    TWO_REVIEWER_TYPE,
    ReviewTestCase,
)
from .factories import (
    make_admin,
    make_group,
    make_preliminary_reviewer,
    make_reviewer,
    make_user,
    pdf,
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
        """A browser only sends the annotated file if the form is multipart.

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
            {"decision": ReviewTask.APPROVE, "comment": "同意送审。"},
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

    def test_reviewer_uploads_annotated_file_via_view(self):
        submission = self._submit()
        assignment = self._assignment(submission, self.reviewer_one)
        self.client.force_login(self.reviewer_one)

        response = self.client.post(
            reverse("reviews:complete", args=(assignment.pk,)),
            {
                "decision": ReviewTask.APPROVE,
                "comment": "已在稿件上批注。",
                "annotated_file": pdf("annotated.pdf"),
            },
        )

        self.assertEqual(response.status_code, 302)
        assignment.refresh_from_db()
        self.assertTrue(assignment.annotated_file)
        self.assertTrue(assignment.annotated_file.name.endswith(".pdf"))

    def test_proposal_upload_rejects_unsupported_extension(self):
        self.client.force_login(self.contact)

        response = self.client.post(
            reverse("projects:group_proposal_update", args=(self.group.pk,)),
            {"proposal": SimpleUploadedFile("plan.txt", b"hello", content_type="text/plain")},
        )

        self.assertEqual(response.status_code, 302)
        self.group.refresh_from_db()
        self.assertNotEqual(self.group.proposal.name, "plan.txt")




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
