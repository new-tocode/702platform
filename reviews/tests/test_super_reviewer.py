"""超级评审：一票敲定某轮。

这个角色的意义是给卡住或有争议的轮次一个了结，所以结论不能由普通评审人的票
反推出来。它同时是「进行中」的看门人：初审中的轮次也在它手里。
"""

from django.urls import reverse

from core.models import AuditLog
from core.registry import get_entries_for_user
from projects.permissions import can_view_group

from ..models import (
    REVIEW_TYPE_INNOVATION_START,
    ArchivedProposal,
    ReviewTask,
    ProjectSubmission,
    preliminary_task_of,
)
from ..services import (
    pending_task_summary,
    ReviewError,
    can_override_review,
    submit_verdict,
    override_blocker,
    override_review,
    submit_for_review,
)
from .base import ReviewTestCase
from .factories import (
    make_group,
    make_preliminary_reviewer,
    make_reviewer,
    make_super_reviewer,
    make_user,
    pdf,
)


class SuperReviewerOverrideTests(ReviewTestCase):
    """A super reviewer settles an in-progress round with one vote.

    The point of the role is to be able to decide a round that is stuck or
    contested, so the verdict must not be re-derived from the ordinary
    reviewers' votes — an earlier 需修改 must not overrule it.
    """

    def setUp(self):
        self.contact = make_user("super-contact")
        self.member = make_user("super-member")
        self.reviewer_one = make_reviewer("super-reviewer-one")
        self.reviewer_two = make_reviewer("super-reviewer-two")
        # 只给敲定资格——这样的账号从不会被抽为普通评审人。
        self.super_reviewer = make_super_reviewer("super-boss")
        self.preliminary = make_preliminary_reviewer("super-preliminary")
        self.outsider = make_user("super-outsider")
        self.group = make_group("超级评审项目组", leader=self.contact, members=[self.member])
    """A super reviewer settles an in-progress round with one vote.

    The point of the role is to be able to decide a round that is stuck or
    contested, so the verdict must not be re-derived from the ordinary
    reviewers' votes — an earlier 需修改 must not overrule it.
    """

    def _override(self, submission, decision=ReviewTask.APPROVE, **kwargs):
        kwargs.setdefault("comment", "超级评审意见。")
        return override_review(
            submission=submission,
            super_reviewer=kwargs.pop("super_reviewer", self.super_reviewer),
            decision=decision,
            **kwargs,
        )

    # --- the vote settles the round -----------------------------------------

    def test_override_approves_the_round_and_releases_the_waiting_reviewers(self):
        submission = self._submit()

        self._override(submission)

        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.APPROVED)
        self.assertIsNotNone(submission.decided_at)
        self.assertEqual(
            set(self.review_tasks(submission).values_list("status", flat=True)),
            {ReviewTask.RELEASED, ReviewTask.COMPLETED},
        )
        override_row = self.review_tasks(submission).get(is_override=True)
        self.assertEqual(override_row.reviewer, self.super_reviewer)
        self.assertEqual(override_row.decision, ReviewTask.APPROVE)
        self.assertEqual(override_row.status, ReviewTask.COMPLETED)
        audit = AuditLog.objects.get(action="reviews.submission.override")
        self.assertEqual(audit.detail["released"], 2)

    def test_override_rejects_the_round(self):
        submission = self._submit()

        self._override(submission, decision=ReviewTask.REVISE)

        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.NEEDS_REVISION)
        self.assertEqual(
            self.review_tasks(submission).filter(status=ReviewTask.RELEASED).count(), 2
        )
        self.assertFalse(ArchivedProposal.objects.filter(submission=submission).exists())

    def test_override_beats_an_earlier_revision_request(self):
        """The super vote must not be re-derived from the ordinary reviewers' votes."""
        submission = self._submit()
        first = self.review_tasks(submission).filter(reviewer=self.reviewer_one).get()
        submit_verdict(
            task=first,
            reviewer=self.reviewer_one,
            decision=ReviewTask.REVISE,
            comment="请补充预算。",
        )

        self._override(submission)

        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.APPROVED)

    def test_override_archives_every_annotated_copy(self):
        submission = self._submit()
        submit_verdict(
            task=self.review_tasks(submission).filter(reviewer=self.reviewer_one).get(),
            reviewer=self.reviewer_one,
            decision=ReviewTask.APPROVE,
            comment="同意。",
            annotated_file=pdf("reviewer-one.pdf"),
        )

        self._override(submission, annotated_file=pdf("super.pdf"))

        archived = ArchivedProposal.objects.filter(submission=submission)
        self.assertEqual(archived.count(), 2)
        # 归档的正是「已完成且通过」的那两条；被释放的那条没有批注文件，不产生归档。
        self.assertEqual(
            set(archived.values_list("source_task_id", flat=True)),
            set(
                self.review_tasks(submission).filter(
                    status=ReviewTask.COMPLETED,
                    decision=ReviewTask.APPROVE,
                ).values_list("pk", flat=True)
            ),
        )

    # --- the released reviewer cannot come back ------------------------------

    def test_a_released_task_can_no_longer_be_submitted(self):
        submission = self._submit()
        released = self.review_tasks(submission).filter(reviewer=self.reviewer_two).get()

        self._override(submission)

        with self.assertRaises(ReviewError):
            submit_verdict(
                task=released,
                reviewer=self.reviewer_two,
                decision=ReviewTask.APPROVE,
                comment="我还是评一下。",
            )
        released.refresh_from_db()
        self.assertEqual(released.status, ReviewTask.RELEASED)

    def test_released_tasks_drop_out_of_the_reminder_count(self):
        submission = self._submit()
        self.assertEqual(pending_task_summary(self.reviewer_one).review, 1)

        self._override(submission)

        self.assertEqual(pending_task_summary(self.reviewer_one).review, 0)

    # --- the override reaches a round waiting on its 初审 ----------------------

    def test_override_settles_a_round_still_in_preliminary(self):
        """初审中也是「进行中」：初审人失联时，超级评审照样能敲定该轮。"""
        submission = self._open_round()

        self._override(submission)

        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.APPROVED)
        preliminary = preliminary_task_of(submission)
        self.assertEqual(preliminary.status, ReviewTask.RELEASED)
        self.assertEqual(pending_task_summary(self.preliminary).preliminary, 0)
        # 这一轮还没分配过评审人，所以被释放的只有那条初审任务。
        self.assertFalse(self.review_tasks(submission).filter(is_override=False).exists())
        audit = AuditLog.objects.get(action="reviews.submission.override")
        # 两道关的等待任务一起放掉：这里就是那一张初审卡。
        self.assertEqual(audit.detail["released"], 1)

    def test_a_released_preliminary_can_no_longer_be_submitted(self):
        submission = self._open_round()
        preliminary = submission.preliminary_task

        self._override(submission)

        with self.assertRaises(ReviewError):
            submit_verdict(
                task=preliminary,
                reviewer=self.preliminary,
                decision=ReviewTask.APPROVE,
                comment="我还是审一下。",
            )
        preliminary.refresh_from_db()
        self.assertEqual(preliminary.status, ReviewTask.RELEASED)

    def test_a_super_reviewer_who_is_also_the_rounds_preliminary_cannot_override_it(self):
        """同一个人不能既放行又敲定同一轮：两票都是他一个人的意见。"""
        submission = self._open_round()
        self.preliminary.is_super_reviewer = True
        self.preliminary.save(update_fields=["is_super_reviewer"])

        self.assertEqual(
            override_blocker(submission=submission, user=self.preliminary),
            "你在本轮已有初审任务，请直接提交那一条",
        )
        with self.assertRaises(ReviewError):
            self._override(submission, super_reviewer=self.preliminary)

    def test_the_released_preliminary_shows_up_in_its_holders_queue(self):
        """被敲定不是凭空消失：初审人的队列里要看得到这一条已释放。"""
        submission = self._open_round()

        self._override(submission)

        self.client.force_login(self.preliminary)
        response = self.client.get(reverse("reviews:queue"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "已释放的初审")
        self.assertContains(response, self.group.name)
        self.assertEqual(
            [row.submission_id for row in response.context["preliminary_released"]],
            [submission.pk],
        )

    def test_a_super_reviewer_keeps_the_access_its_own_vote_earned(self):
        """资格并存时授权取并集：敲定之后仍看得到自己投过票的组。"""
        submission = self._submit()

        self._override(submission)

        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.APPROVED)
        self.assertTrue(can_view_group(self.super_reviewer, self.group))

    # --- who may not override ------------------------------------------------

    def test_a_super_reviewer_holding_a_task_on_the_round_cannot_override_it(self):
        submission = self._submit()
        ReviewTask.objects.create(
            submission=submission, stage=ReviewTask.REVIEW, reviewer=self.super_reviewer
        )

        self.assertFalse(
            can_override_review(submission=submission, user=self.super_reviewer)
        )
        with self.assertRaises(ReviewError):
            self._override(submission)

    def test_a_plain_reviewer_cannot_override(self):
        submission = self._submit()

        self.assertFalse(
            can_override_review(submission=submission, user=self.reviewer_one)
        )
        with self.assertRaises(ReviewError):
            self._override(submission, super_reviewer=self.reviewer_one)

    def test_the_submitter_cannot_override(self):
        submission = self._submit()
        self.contact.is_super_reviewer = True
        self.contact.save(update_fields=["is_super_reviewer"])

        with self.assertRaises(ReviewError):
            self._override(submission, super_reviewer=self.contact)

    def test_a_group_member_cannot_override(self):
        submission = self._submit()
        self.member.is_super_reviewer = True
        self.member.save(update_fields=["is_super_reviewer"])

        with self.assertRaises(ReviewError):
            self._override(submission, super_reviewer=self.member)

    def test_a_settled_round_cannot_be_overridden(self):
        submission = self._submit()
        for assignment in self.review_tasks(submission).all():
            submit_verdict(
                task=assignment,
                reviewer=assignment.reviewer,
                decision=ReviewTask.APPROVE,
                comment="同意。",
            )

        with self.assertRaises(ReviewError):
            self._override(submission, decision=ReviewTask.REVISE)

    # --- reach: queue and group visibility -----------------------------------

    def test_the_review_entry_is_visible_to_super_reviewers(self):
        keys = {entry.key for entry in get_entries_for_user(self.super_reviewer)}

        self.assertIn("reviews.queue", keys)

    def test_super_reviewer_sees_a_group_only_while_it_has_an_open_round(self):
        self.assertFalse(can_view_group(self.super_reviewer, self.group))
        submission = self._open_round()
        # 初审中也算进行中：要看项目书才谈得上敲定。
        self.assertTrue(can_view_group(self.super_reviewer, self.group))
        preliminary = submission.preliminary_task
        submit_verdict(
            task=preliminary,
            reviewer=preliminary.reviewer,
            decision=ReviewTask.APPROVE,
            comment="同意送审。",
        )
        self.assertTrue(can_view_group(self.super_reviewer, self.group))

        for assignment in self.review_tasks(submission).all():
            submit_verdict(
                task=assignment,
                reviewer=assignment.reviewer,
                decision=ReviewTask.APPROVE,
                comment="同意。",
            )

        self.assertFalse(can_view_group(self.super_reviewer, self.group))

    def test_queue_lists_a_round_waiting_on_its_preliminary(self):
        submission = self._open_round()
        self.client.force_login(self.super_reviewer)

        response = self.client.get(reverse("reviews:queue"))

        self.assertContains(response, "初审中")
        rows = response.context["open_rounds"]
        self.assertEqual([row["submission"].pk for row in rows], [submission.pk])
        # 这一轮尚未分配评审人，超级评审可以行使（不标注「不可行使」）。
        self.assertIsNone(rows[0]["blocker"])

    def test_queue_lists_every_open_round_for_a_super_reviewer(self):
        other = make_group("另一个组", leader=self.contact)
        self._submit()
        submit_for_review(
            group=other,
            submitter=self.contact,
            review_type=REVIEW_TYPE_INNOVATION_START,
        )
        self.client.force_login(self.super_reviewer)

        response = self.client.get(reverse("reviews:queue"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "全部进行中")
        self.assertContains(response, "超级评审项目组")
        self.assertContains(response, "另一个组")
        self.assertEqual(len(response.context["open_rounds"]), 2)
        # 这条账号两条都能行使，所以给的是可操作按钮、没有「不可行使」标注。
        self.assertContains(response, "查看项目书并决定")
        self.assertNotContains(response, "不可行使")

    def test_queue_explains_why_a_round_cannot_be_overridden(self):
        """无权行使时不要把按钮写成「并决定」——那是在承诺做不到的事。"""
        submission = self._submit()
        self.contact.is_super_reviewer = True
        self.contact.save(update_fields=["is_super_reviewer"])
        self.client.force_login(self.contact)

        response = self.client.get(reverse("reviews:queue"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "不可行使")
        self.assertContains(response, "你是本轮的提交人")
        self.assertNotContains(response, "查看项目书并决定")
        rows = response.context["open_rounds"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["submission"].pk, submission.pk)
        self.assertEqual(rows[0]["blocker"], "你是本轮的提交人")

    def test_override_blocker_names_each_reason(self):
        submission = self._submit()

        self.assertIsNone(
            override_blocker(submission=submission, user=self.super_reviewer)
        )
        self.assertEqual(
            override_blocker(submission=submission, user=self.reviewer_one),
            "没有超级评审资格",
        )
        self.contact.is_super_reviewer = True
        self.contact.save(update_fields=["is_super_reviewer"])
        self.assertEqual(
            override_blocker(submission=submission, user=self.contact),
            "你是本轮的提交人",
        )
        self.member.is_super_reviewer = True
        self.member.save(update_fields=["is_super_reviewer"])
        self.assertEqual(
            override_blocker(submission=submission, user=self.member),
            "你是本项目组成员",
        )
        ReviewTask.objects.create(
            submission=submission, stage=ReviewTask.REVIEW, reviewer=self.super_reviewer
        )
        self.assertEqual(
            override_blocker(submission=submission, user=self.super_reviewer),
            "你在本轮已有评审任务，请直接提交那一条",
        )
        self.preliminary.is_super_reviewer = True
        self.preliminary.save(update_fields=["is_super_reviewer"])
        self.assertEqual(
            override_blocker(submission=submission, user=self.preliminary),
            "你是本轮的初审人，已经就该轮给出初审意见",
        )

    def test_queue_has_no_open_rounds_section_for_a_plain_reviewer(self):
        self._submit()
        self.client.force_login(self.reviewer_one)

        response = self.client.get(reverse("reviews:queue"))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("open_rounds", response.context)
        self.assertNotContains(response, "全部进行中")

    # --- the views -----------------------------------------------------------

    def test_super_reviewer_overrides_via_view(self):
        submission = self._submit()
        self.client.force_login(self.super_reviewer)

        response = self.client.post(
            reverse("reviews:override", args=(submission.pk,)),
            {"override-decision": ReviewTask.APPROVE, "override-comment": "同意。"},
        )

        self.assertEqual(response.status_code, 302)
        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.APPROVED)

    def test_override_view_requires_a_comment(self):
        submission = self._submit()
        self.client.force_login(self.super_reviewer)

        response = self.client.post(
            reverse("reviews:override", args=(submission.pk,)),
            {"override-decision": ReviewTask.APPROVE, "override-comment": ""},
        )

        self.assertEqual(response.status_code, 302)
        submission.refresh_from_db()
        self.assertEqual(submission.status, ProjectSubmission.PENDING)

    def test_override_view_rejects_plain_reviewers_and_get(self):
        submission = self._submit()
        url = reverse("reviews:override", args=(submission.pk,))
        self.client.force_login(self.reviewer_one)
        self.assertEqual(
            self.client.post(url, {"override-decision": "approve", "override-comment": "x"}).status_code,
            403,
        )

        self.client.force_login(self.super_reviewer)
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_group_detail_offers_the_override_form_only_to_super_reviewers(self):
        submission = self._submit()
        url = reverse("projects:group_detail", args=(self.group.pk,))

        self.client.force_login(self.reviewer_one)
        plain = self.client.get(url)
        self.assertNotContains(plain, "一票决定")
        self.assertFalse(plain.context["can_override"])

        self.client.force_login(self.super_reviewer)
        boss = self.client.get(url)
        self.assertContains(boss, "一票决定")
        self.assertTrue(boss.context["can_override"])
        self.assertEqual(
            boss.context["latest_submission"].pk, submission.pk
        )

    def test_group_detail_shows_a_released_task_as_released(self):
        submission = self._submit()
        self._override(submission)
        self.client.force_login(self.member)

        response = self.client.get(reverse("projects:group_detail", args=(self.group.pk,)))

        self.assertContains(response, "已释放")
        self.assertContains(response, "超级评审")
        # 超级评审同样匿名：页面上不出现其账号。
        self.assertNotContains(response, self.super_reviewer.username)

    # --- markup stays well formed -------------------------------------------

    def test_queue_markup_stays_balanced(self):
        """Django 模板不校验 HTML 嵌套：区块对了但标签没配平照样渲染 200。"""
        submission = self._submit()
        self.client.force_login(self.super_reviewer)

        with_open_rounds = self.client.get(reverse("reviews:queue"))
        self._override(submission)
        with_released = self.client.get(reverse("reviews:queue"))
        # 初审人那一侧的面板（待初审 / 已完成的初审）另走一趟。
        self.client.force_login(self.preliminary)
        preliminary_side = self.client.get(reverse("reviews:queue"))

        for response in (with_open_rounds, with_released, preliminary_side):
            html = response.content.decode()
            self.assertEqual(html.count("<div"), html.count("</div>"))

    def test_group_detail_markup_stays_balanced(self):
        submission = self._submit()
        self.client.force_login(self.super_reviewer)

        with_reviewers = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )
        self._override(submission)
        settled = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )
        # 再开一轮、停在初审中：初审人的「我的初审」面板也渲染一遍。
        self._open_round()
        self.client.force_login(self.preliminary)
        in_preliminary = self.client.get(
            reverse("projects:group_detail", args=(self.group.pk,))
        )

        for response in (with_reviewers, settled, in_preliminary):
            html = response.content.decode()
            self.assertEqual(html.count("<div"), html.count("</div>"))


