"""后台的整轮删除，以及「单条任务不能删」这道反向的守卫。

删整轮与删一条任务是两条相反的规则，必须同时成立：整轮删得掉（它是留错的
记录），单条删不掉（删掉它等于悄悄改变这一轮需要几人）。
"""

from django.urls import reverse

from core.models import AuditLog

from ..models import (
    ArchivedProposal,
    ReviewTask,
    ProjectSubmission,
)
from .base import ReviewTestCase
from .factories import (
    make_admin,
    make_group,
    make_preliminary_reviewer,
    make_reviewer,
    make_user,
)


class AdminRoundDeletionTests(ReviewTestCase):
    """A round is deleted as a whole, together with its 初审与评审任务.

    The per-task guards still refuse a single row — that would silently change how
    many reviewers the round needs — but that same guard used to make the round
    undeletable, because Django asks the task's admin about the tasks a round
    deletion would carry away. The two rules must coexist.
    """

    def setUp(self):
        self.admin = make_admin("del-admin")
        self.contact = make_user("del-contact")
        self.reviewer_one = make_reviewer("del-reviewer-one")
        self.reviewer_two = make_reviewer("del-reviewer-two")
        self.preliminary = make_preliminary_reviewer("del-preliminary")
        # 只需要「有项目书」这一事实，不读文件内容，所以不落盘。
        self.group = make_group("删除项目组", leader=self.contact, write_proposal=False)
    """A round is deleted as a whole, together with its review tasks.

    ``ReviewTaskAdmin`` still refuses to delete a single task — that would
    silently change how many reviewers the round needs. But that guard also used
    to make the round undeletable, because Django asks the task's admin about the
    tasks a round deletion would carry away. The two rules must coexist: whole
    rounds go, individual tasks stay.
    """

    def _delete_url(self, submission):
        return reverse(
            "admin:reviews_projectsubmission_delete", args=(submission.pk,)
        )

    def test_admin_deletes_a_round_together_with_its_tasks(self):
        submission = self._submit()
        submission_pk = submission.pk
        assignment_pks = list(self.review_tasks(submission).values_list("pk", flat=True))
        preliminary_pk = submission.preliminary_task.pk
        self.client.force_login(self.admin)

        response = self.client.post(self._delete_url(submission), {"post": "yes"})

        self.assertEqual(response.status_code, 302)
        self.assertFalse(ProjectSubmission.objects.filter(pk=submission_pk).exists())
        self.assertFalse(ReviewTask.objects.filter(pk__in=assignment_pks).exists())
        self.assertFalse(ReviewTask.objects.filter(pk=preliminary_pk).exists())
        audit = AuditLog.objects.get(action="reviews.submission.delete")
        self.assertEqual(audit.detail["submission_id"], submission_pk)
        # tasks 是本轮全部任务：一条初审 + 两条评审；preliminary 单独记有无初审。
        self.assertEqual(audit.detail["tasks"], 3)
        self.assertEqual(audit.detail["preliminary"], 1)

    def test_admin_deletes_a_round_still_in_preliminary(self):
        """初审同样是整轮的一部分：删掉的轮次不会留下孤儿初审任务。"""
        submission = self._open_round()
        submission_pk = submission.pk
        preliminary_pk = submission.preliminary_task.pk
        self.client.force_login(self.admin)

        response = self.client.post(self._delete_url(submission), {"post": "yes"})

        self.assertEqual(response.status_code, 302)
        self.assertFalse(ProjectSubmission.objects.filter(pk=submission_pk).exists())
        self.assertFalse(ReviewTask.objects.filter(pk=preliminary_pk).exists())
        audit = AuditLog.objects.get(action="reviews.submission.delete")
        # 这一轮没有评审任务，只有那一条初审。
        self.assertEqual(audit.detail["tasks"], 1)
        self.assertEqual(audit.detail["preliminary"], 1)

    def test_admin_deletion_is_refused_once_the_round_is_archived(self):
        submission = self._submit()
        ArchivedProposal.objects.create(
            group=self.group,
            submission=submission,
            source_task=self.review_tasks(submission).first(),
            file="review_archives/kept.pdf",
        )
        submission_pk = submission.pk
        self.client.force_login(self.admin)

        response = self.client.post(self._delete_url(submission), {"post": "yes"})

        # PROTECT 拦住级联：确认页被重新渲染，对象仍在。
        self.assertEqual(response.status_code, 200)
        self.assertTrue(ProjectSubmission.objects.filter(pk=submission_pk).exists())

    def test_the_single_task_guard_stays_closed(self):
        """删整轮放开的同时，单独删一条任务仍然被拒。"""
        submission = self._submit()
        assignment = self.review_tasks(submission).first()

        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("admin:reviews_reviewtask_delete", args=(assignment.pk,))
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(ReviewTask.objects.filter(pk=assignment.pk).exists())

    def test_the_single_preliminary_guard_stays_closed(self):
        """初审任务也一样：单独删掉它会让这一轮再也进不去评审。"""
        submission = self._open_round()
        preliminary = submission.preliminary_task

        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("admin:reviews_reviewtask_delete", args=(preliminary.pk,))
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(ReviewTask.objects.filter(pk=preliminary.pk).exists())


