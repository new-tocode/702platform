"""Journal-style peer review of project proposals.

Each :class:`ProjectSubmission` is one review round of a project group's
proposal. A round starts in the hands of one :class:`PreliminaryReview` (初审):
that single reviewer passes the proposal on — which is when the round draws the
reviewers its type calls for — or sends it back for revision. From then on
:class:`ReviewAssignment` records one reviewer's verdict, and a submission is
approved only when every assignment is complete and every verdict approves.

The proposal itself is **not** copied here: reviewers download the project
group's current proposal (``ProjectGroup.proposal``) from the group detail page,
so there is a single stored file per group.

How many reviewers a round needs depends on the type the submitter picks
(``REVIEWER_QUOTA``): competition rounds need three, an innovation project needs
one at kick-off and two at mid-term/final. A reviewer may attach an annotated
copy of the proposal along with the verdict; once the round is approved those
annotated copies are archived as :class:`ArchivedProposal` records.

The ``review_type`` labels are **platform-local tags** and deliberately have no
foreign key to ``competitions.Competition``.
"""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from projects.models import ProjectGroup
from projects.validators import validate_proposal_file

from . import lifecycle


REVIEW_TYPE_COMPETITION_PROJECT = "competition_project"
REVIEW_TYPE_COMPETITION_PROVINCIAL = "competition_provincial"
REVIEW_TYPE_COMPETITION_NATIONAL = "competition_national"
REVIEW_TYPE_INNOVATION_START = "innovation_start"
REVIEW_TYPE_INNOVATION_MIDTERM = "innovation_midterm"
REVIEW_TYPE_INNOVATION_FINAL = "innovation_final"

REVIEW_TYPE_CHOICES = (
    (REVIEW_TYPE_COMPETITION_PROJECT, "竞赛立项"),
    (REVIEW_TYPE_COMPETITION_PROVINCIAL, "竞赛省赛"),
    (REVIEW_TYPE_COMPETITION_NATIONAL, "竞赛国赛"),
    (REVIEW_TYPE_INNOVATION_START, "大创立项"),
    (REVIEW_TYPE_INNOVATION_MIDTERM, "大创中期"),
    (REVIEW_TYPE_INNOVATION_FINAL, "大创结题"),
)

#: Reviewers required per submission type; the single place that decides it.
REVIEWER_QUOTA = {
    REVIEW_TYPE_COMPETITION_PROJECT: 3,
    REVIEW_TYPE_COMPETITION_PROVINCIAL: 3,
    REVIEW_TYPE_COMPETITION_NATIONAL: 3,
    REVIEW_TYPE_INNOVATION_START: 1,
    REVIEW_TYPE_INNOVATION_MIDTERM: 2,
    REVIEW_TYPE_INNOVATION_FINAL: 2,
}

#: Rounds created before submission types existed keep the original two-reviewer rule.
DEFAULT_REVIEWERS = 2


def _neutral_name(filename):
    """Return a uuid-based storage name that carries no user information."""
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"{uuid.uuid4().hex}.{extension}"


def upload_annotated_proposal(instance, filename):
    """Store a reviewer's annotated copy under a name that hides the reviewer.

    Reviewer attachments must never carry the reviewer's name into storage: the
    anonymous-by-default contract would leak through a filename such as
    ``zhangsan-批注.docx``. The download views hand out a neutral
    ``Content-Disposition`` on top of this.
    """
    return f"review_annotations/{timezone.now():%Y/%m}/{_neutral_name(filename)}"


def upload_archived_proposal(instance, filename):
    """Store an archived annotated copy under the same neutral naming."""
    return f"review_archives/{timezone.now():%Y/%m}/{_neutral_name(filename)}"


class ProjectSubmission(models.Model):
    #: 取值、迁移表与拒绝文案都在 :mod:`reviews.lifecycle`；模型上留同名别名，
    #: 历史代码与模板的语义不变。
    PRELIMINARY_PENDING = lifecycle.PRELIMINARY_PENDING
    PENDING = lifecycle.PENDING
    APPROVED = lifecycle.APPROVED
    NEEDS_REVISION = lifecycle.NEEDS_REVISION
    STATUS_CHOICES = lifecycle.STATUS_CHOICES
    OPEN_STATUSES = lifecycle.OPEN_STATUSES

    group = models.ForeignKey(
        ProjectGroup,
        on_delete=models.PROTECT,
        related_name="submissions",
        verbose_name="项目组",
    )
    round = models.PositiveIntegerField("评审轮次", default=1)
    review_type = models.CharField(
        "评审类型",
        max_length=32,
        choices=REVIEW_TYPE_CHOICES,
        blank=True,
        default="",
        help_text="决定本轮需要几名评审人；升级前创建的送审留空，沿用两人制。",
    )
    message = models.TextField("提交说明", blank=True)
    status = models.CharField(
        "状态",
        max_length=20,
        choices=STATUS_CHOICES,
        default=PRELIMINARY_PENDING,
        help_text="新建的轮次从「初审中」开始；初审通过后才进入「评审中」。",
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="project_submissions",
        verbose_name="提交人",
    )
    submitted_at = models.DateTimeField("提交时间", auto_now_add=True)
    decided_at = models.DateTimeField("完成时间", null=True, blank=True)

    class Meta:
        verbose_name = "项目书送审"
        verbose_name_plural = "项目书送审"
        ordering = ("-submitted_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("group", "round"),
                name="unique_group_submission_round",
            ),
        ]
        indexes = [
            models.Index(fields=("group", "status")),
            models.Index(fields=("status", "-submitted_at")),
        ]

    def __str__(self):
        return f"{self.group} 第 {self.round} 轮送审"

    @property
    def is_approved(self):
        return self.status == self.APPROVED

    @property
    def is_needs_revision(self):
        return self.status == self.NEEDS_REVISION

    @property
    def is_preliminary_pending(self):
        return self.status == self.PRELIMINARY_PENDING

    @property
    def status_tone(self):
        """模板语气：``chip-{{ status_tone }}``／``.v.{{ status_tone }}``。

        进行中的两个状态给空串，与今天「只有已通过／需修改才套色」的输出一致。
        """
        return lifecycle.STATUS_TONES.get(self.status, "")

    @property
    def is_open(self):
        """Whether the round is still running — 初审中 or 评审中."""
        return self.status in self.OPEN_STATUSES

    @property
    def required_reviewers(self):
        """How many reviewers this round needs; rounds without a type keep the old rule."""
        return REVIEWER_QUOTA.get(self.review_type, DEFAULT_REVIEWERS)

    @property
    def completed_count(self):
        return self.assignments.filter(status=ReviewAssignment.COMPLETED).count()

    @property
    def pending_count(self):
        return self.assignments.filter(status=ReviewAssignment.PENDING).count()

    @property
    def open_task_count(self):
        """Tasks of this round still awaiting a verdict, 初审 included.

        ``pending_count`` counts review tasks only, which is what the reviewer
        progress figures want; this is the one a super reviewer is about to let
        go, so the pending 初审 must be in it.
        """
        count = self.pending_count
        preliminary = preliminary_review_of(self)
        if preliminary is not None and preliminary.status == PreliminaryReview.PENDING:
            count += 1
        return count


class ReviewAssignment(models.Model):
    """One reviewer's task on one round.

    ``RELEASED`` is the end state of a task whose round was decided by a super
    reviewer before this reviewer got to it: the task is no longer in 待评审, so
    it stops counting towards reminders and can no longer be submitted — but the
    row stays, so the roster still shows who had been asked.
    """

    PENDING = "pending"
    COMPLETED = "completed"
    RELEASED = "released"
    STATUS_CHOICES = (
        (PENDING, "待评审"),
        (COMPLETED, "已完成"),
        (RELEASED, "已释放"),
    )

    APPROVE = "approve"
    REVISE = "revise"
    DECISION_CHOICES = (
        (APPROVE, "通过"),
        (REVISE, "需修改"),
    )

    submission = models.ForeignKey(
        ProjectSubmission,
        on_delete=models.CASCADE,
        related_name="assignments",
        verbose_name="送审",
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="review_assignments",
        verbose_name="评审人",
    )
    status = models.CharField(
        "状态",
        max_length=16,
        choices=STATUS_CHOICES,
        default=PENDING,
    )
    decision = models.CharField(
        "评审决定",
        max_length=16,
        choices=DECISION_CHOICES,
        blank=True,
    )
    comment = models.TextField("评审意见", blank=True)
    is_override = models.BooleanField(
        "超级评审决定",
        default=False,
        help_text="该行来自超级评审的一票决定：本轮结论由它单独敲定，等待中的任务（初审一并）随即被释放。",
    )
    annotated_file = models.FileField(
        "批注版项目书",
        upload_to=upload_annotated_proposal,
        blank=True,
        validators=[validate_proposal_file],
        help_text="选填；支持 doc、docx、pdf。请勿在文件属性中保留可识别个人身份的信息。",
    )
    assigned_at = models.DateTimeField("分配时间", auto_now_add=True)
    completed_at = models.DateTimeField("完成时间", null=True, blank=True)

    class Meta:
        verbose_name = "评审任务"
        verbose_name_plural = "评审任务"
        ordering = ("status", "-assigned_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("submission", "reviewer"),
                name="unique_submission_reviewer",
            ),
        ]
        indexes = [
            models.Index(fields=("reviewer", "status")),
        ]

    def __str__(self):
        return f"{self.reviewer} 评审 {self.submission}"

    @property
    def is_pending(self):
        return self.status == self.PENDING

    @property
    def is_completed(self):
        return self.status == self.COMPLETED

    @property
    def is_released(self):
        return self.status == self.RELEASED

    @property
    def decision_tone(self):
        """结论对应的 chip 语气：通过=ok，需修改=warn。"""
        return "ok" if self.decision == self.APPROVE else "warn"


class PreliminaryReview(models.Model):
    """The 初审 gate of one round: one reviewer decides whether it goes on.

    A round is submitted to exactly one 初审人 — the one-to-one is the point of
    the stage, not an accident — and only their 通过 draws the round's ordinary
    reviewers. A 打回 sends the round straight back to the group, so a proposal
    that is not ready never spends the panel's time.

    Statuses mirror :class:`ReviewAssignment`, ``RELEASED`` included: it is the
    end state of a task whose round a super reviewer settled first.
    """

    #: 初审与评审回答的是同一个问题——放行还是打回——所以共用同一对结论取值，
    #: 免得两处各写一份再慢慢长歪。
    APPROVE = ReviewAssignment.APPROVE
    REVISE = ReviewAssignment.REVISE
    DECISION_CHOICES = ReviewAssignment.DECISION_CHOICES

    PENDING = "pending"
    COMPLETED = "completed"
    RELEASED = "released"
    STATUS_CHOICES = (
        (PENDING, "待初审"),
        (COMPLETED, "已初审"),
        (RELEASED, "已释放"),
    )

    submission = models.OneToOneField(
        ProjectSubmission,
        on_delete=models.CASCADE,
        related_name="preliminary_review",
        verbose_name="送审",
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="preliminary_reviews",
        verbose_name="初审人",
        help_text="须有初审资格（User.is_preliminary_reviewer）。",
    )
    status = models.CharField(
        "状态",
        max_length=16,
        choices=STATUS_CHOICES,
        default=PENDING,
    )
    decision = models.CharField(
        "初审决定",
        max_length=16,
        choices=DECISION_CHOICES,
        blank=True,
    )
    comment = models.TextField("初审意见", blank=True)
    assigned_at = models.DateTimeField("分配时间", auto_now_add=True)
    completed_at = models.DateTimeField("完成时间", null=True, blank=True)

    class Meta:
        verbose_name = "初审任务"
        verbose_name_plural = "初审任务"
        ordering = ("-assigned_at", "-id")
        indexes = [
            models.Index(fields=("reviewer", "status")),
        ]

    def __str__(self):
        return f"{self.reviewer} 初审 {self.submission}"

    @property
    def is_pending(self):
        return self.status == self.PENDING

    @property
    def is_completed(self):
        return self.status == self.COMPLETED

    @property
    def is_released(self):
        return self.status == self.RELEASED

    @property
    def decision_tone(self):
        """结论对应的 chip 语气：通过=ok，需修改=warn。"""
        return "ok" if self.decision == self.APPROVE else "warn"


def preliminary_review_of(submission):
    """This round's 初审 task, or ``None``.

    Rounds created before the 初审 stage existed have none, so every caller has
    to cope with the absence. The row is read fresh instead of through the
    reverse one-to-one accessor: that accessor caches whatever it saw first, and
    the row is mutated in place — it gets a verdict, a super reviewer releases
    it, an administrator swaps its holder — so a cached copy goes stale in
    exactly the places where it decides something.
    """
    if submission is None or submission.pk is None:
        return None
    return PreliminaryReview.objects.filter(submission_id=submission.pk).first()


class ArchivedProposal(models.Model):
    """An approved round's annotated proposal, kept as the group's record.

    One row per reviewer who actually attached an annotated copy — reviewers who
    answered with text only produce no row, and the original proposal is never
    duplicated here. Rows are written once when a round turns ``approved`` and
    are immutable afterwards.
    """

    group = models.ForeignKey(
        ProjectGroup,
        on_delete=models.PROTECT,
        related_name="archived_proposals",
        verbose_name="项目组",
    )
    submission = models.ForeignKey(
        ProjectSubmission,
        on_delete=models.PROTECT,
        related_name="archived_proposals",
        verbose_name="送审",
    )
    source_assignment = models.ForeignKey(
        ReviewAssignment,
        on_delete=models.PROTECT,
        related_name="archived_proposals",
        verbose_name="来源评审任务",
    )
    file = models.FileField(
        "批注版项目书",
        upload_to=upload_archived_proposal,
    )
    archived_at = models.DateTimeField("归档时间", auto_now_add=True)

    class Meta:
        verbose_name = "批注版项目书归档"
        verbose_name_plural = "批注版项目书归档"
        ordering = ("-archived_at", "-id")
        constraints = [
            # Archiving runs inside the verdict aggregation, which may be
            # retried; one archive per source assignment keeps it idempotent.
            models.UniqueConstraint(
                fields=("source_assignment",),
                name="unique_archived_proposal_assignment",
            ),
        ]
        indexes = [
            models.Index(fields=("group", "-archived_at")),
        ]

    def __str__(self):
        return f"{self.group} 第 {self.submission.round} 轮的批注版项目书"


class ReviewerLeaveQuerySet(models.QuerySet):
    def active(self, at=None):
        """Leaves whose window covers ``at`` (defaults to now)."""
        moment = at or timezone.now()
        return self.filter(starts_at__lte=moment, ends_at__gt=moment)

    def open(self, at=None):
        """Leaves that have not ended yet — the ones a reviewer may still edit."""
        moment = at or timezone.now()
        return self.filter(ends_at__gt=moment)


class ReviewerLeave(models.Model):
    """A window during which a reviewer takes no new review requests.

    The window covers both kinds of task a reviewer may be handed — a 初审 and an
    ordinary 评审 — because it describes the person's availability, not a stage.
    Leave never touches ``User.is_reviewer`` or ``User.is_preliminary_reviewer``:
    the qualifications stay and the reviewer is merely skipped when a draw runs.
    Because the window is stored as two timestamps, eligibility returns on its
    own once ``ends_at`` passes — there is no scheduled job to run and nothing to
    undo.

    A reviewer has at most one open window at a time; re-registering edits that
    window rather than stacking a second one. Overlap cannot be expressed as a
    database constraint because PostgreSQL index predicates must be immutable
    and ``now()`` is not, so the rule lives in ``reviews.services``.
    """

    LEAVE_UPCOMING = "upcoming"
    LEAVE_ACTIVE = "active"
    LEAVE_ENDED = "ended"
    STATE_LABELS = {
        LEAVE_UPCOMING: "未开始",
        LEAVE_ACTIVE: "请假中",
        LEAVE_ENDED: "已结束",
    }

    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reviewer_leaves",
        verbose_name="评审人",
    )
    starts_at = models.DateTimeField("请假开始")
    ends_at = models.DateTimeField("请假结束")
    reason = models.TextField("事由", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="created_reviewer_leaves",
        verbose_name="登记人",
        help_text="首次登记该请假的账号：本人自助登记时为自己，管理员代登记时为该管理员。",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    objects = ReviewerLeaveQuerySet.as_manager()

    class Meta:
        verbose_name = "评审人请假"
        verbose_name_plural = "评审人请假"
        ordering = ("-starts_at", "-id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="reviewer_leave_ends_after_starts",
            ),
        ]
        indexes = [
            models.Index(fields=("reviewer", "starts_at", "ends_at")),
            models.Index(fields=("starts_at", "ends_at")),
        ]

    def __str__(self):
        return f"{self.reviewer} 请假 {self.starts_at:%Y-%m-%d %H:%M} 至 {self.ends_at:%Y-%m-%d %H:%M}"

    def covers(self, moment=None):
        """Whether this window covers ``moment`` (defaults to now)."""
        moment = moment or timezone.now()
        return self.starts_at <= moment < self.ends_at

    @property
    def state(self):
        """Which of the three states this window is in right now."""
        now = timezone.now()
        if self.starts_at > now:
            return self.LEAVE_UPCOMING
        if self.ends_at > now:
            return self.LEAVE_ACTIVE
        return self.LEAVE_ENDED

    @property
    def is_active(self):
        return self.state == self.LEAVE_ACTIVE

    @property
    def state_label(self):
        return self.STATE_LABELS[self.state]
