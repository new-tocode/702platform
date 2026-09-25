"""Journal-style peer review of project proposals.

Each :class:`ProjectSubmission` is one review round of a project group's
proposal. A round starts in the hands of one :class:`ReviewTask` (初审):
that single reviewer passes the proposal on — which is when the round draws the
reviewers its type calls for — or sends it back for revision. From then on
:class:`ReviewTask` records one reviewer's verdict, and a submission is
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

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.storage import neutral_upload_to, private_storage
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
    (REVIEW_TYPE_COMPETITION_PROJECT, _("竞赛立项")),
    (REVIEW_TYPE_COMPETITION_PROVINCIAL, _("竞赛省赛")),
    (REVIEW_TYPE_COMPETITION_NATIONAL, _("竞赛国赛")),
    (REVIEW_TYPE_INNOVATION_START, _("大创立项")),
    (REVIEW_TYPE_INNOVATION_MIDTERM, _("大创中期")),
    (REVIEW_TYPE_INNOVATION_FINAL, _("大创结题")),
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


#: 评审人的批注版与归档件：落盘名一律 uuid。
#:
#: 匿名是评审的硬约束，而文件名是最容易漏的一处——``zhangsan-批注.docx`` 这样的
#: 名字会把评审人直接写进存储层，再跟着备份与运维的 ls 一路扩散出去。命名口径与
#: 其他受保护上传件统一到 core.storage，只在目录前缀上区分。
upload_annotated_proposal = neutral_upload_to("review_annotations")
upload_archived_proposal = neutral_upload_to("review_archives")


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

        进行中给 ``on``（项目组列表的 chip 用它），详情页的 ``.v`` 只有
        ``.ok``／``.warn`` 两条样式，多出来的类不落地任何外观。
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
    def preliminary_task(self):
        """本轮的初审任务（模板用；配合 prefetch_related("tasks") 不额外查询）。

        服务层请用 :func:`preliminary_task_of`：它会现查一遍，避开缓存里的旧副本。
        """
        return next((task for task in self.tasks.all() if task.is_preliminary), None)

    @property
    def review_tasks(self):
        """本轮的评审任务，顺序沿用模型默认排序（模板用）。"""
        return [task for task in self.tasks.all() if task.is_review]

    @property
    def completed_count(self):
        return self.tasks.filter(
            stage=ReviewTask.REVIEW, status=ReviewTask.COMPLETED
        ).count()

    @property
    def open_task_count(self):
        """本轮还没交的任务数，两道关都算。

        这个数字是超级评审即将放掉的量，所以待初审也算进来；要看某一关自己的
        进度，用 ``completed_count``。
        """
        return self.tasks.filter(status=ReviewTask.PENDING).count()


class ReviewTask(models.Model):
    """一轮送审里的一张任务卡：初审一道关，评审一个评审团。

    两道关的任务**形状相同**——同一个持有人概念、同一个状态机、同一对结论、同样的
    改派与释放规则——所以只有一张表，``stage`` 说明这是哪一道。差异只有三处，都由
    约束或 :data:`reviews.lifecycle.STAGES` 表达：

    * 一轮恰好一条初审（``unique_preliminary_task_per_submission``）；
    * 批注版项目书只有评审阶段会填（初审给的是理由，不是稿子）；
    * 超级评审那一票属于评审阶段（``override_is_review_stage_only``）。

    ``RELEASED`` 是「本轮已被超级评审敲定，这张卡不必再交」的终态：不再计入待办、
    不能再提交，但行保留——名单上仍看得出曾请过谁。
    """

    PRELIMINARY = lifecycle.STAGE_PRELIMINARY
    REVIEW = lifecycle.STAGE_REVIEW
    STAGE_CHOICES = lifecycle.STAGE_CHOICES

    PENDING = lifecycle.TASK_PENDING
    COMPLETED = lifecycle.TASK_COMPLETED
    RELEASED = lifecycle.TASK_RELEASED
    STATUS_CHOICES = lifecycle.TASK_STATUS_CHOICES

    APPROVE = lifecycle.DECISION_APPROVE
    REVISE = lifecycle.DECISION_REVISE
    DECISION_CHOICES = lifecycle.DECISION_CHOICES

    submission = models.ForeignKey(
        ProjectSubmission,
        on_delete=models.CASCADE,
        related_name="tasks",
        verbose_name="送审",
    )
    stage = models.CharField("阶段", max_length=16, choices=STAGE_CHOICES)
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="review_tasks",
        verbose_name="评审人",
    )
    status = models.CharField(
        "状态",
        max_length=16,
        choices=STATUS_CHOICES,
        default=PENDING,
    )
    decision = models.CharField(
        "结论",
        max_length=16,
        choices=DECISION_CHOICES,
        blank=True,
    )
    comment = models.TextField("意见", blank=True)
    is_override = models.BooleanField(
        "超级评审决定",
        default=False,
        help_text="该行来自超级评审的一票决定：本轮结论由它单独敲定，等待中的任务随即被释放。",
    )
    annotated_file = models.FileField(
        "批注版项目书",
        upload_to=upload_annotated_proposal,
        storage=private_storage,
        blank=True,
        validators=[validate_proposal_file],
        help_text="选填；支持 doc、docx、pdf。请勿在文件属性中保留可识别个人身份的信息。",
    )
    assigned_at = models.DateTimeField("分配时间", auto_now_add=True)
    completed_at = models.DateTimeField("完成时间", null=True, blank=True)

    class Meta:
        verbose_name = "评审任务"
        verbose_name_plural = "评审任务"
        ordering = ("status", "stage", "-assigned_at", "-id")
        constraints = [
            # 一人一轮一席：初审人不会被抽为同一轮的评审人，所以这条约束与所有
            # 合法路径相容，且把「一人两票」挡在数据库层。
            models.UniqueConstraint(
                fields=("submission", "reviewer"),
                name="unique_submission_task_reviewer",
            ),
            # 一轮恰好一条初审；升级前留下的老轮次没有，所以允许零条。
            models.UniqueConstraint(
                fields=("submission",),
                condition=models.Q(stage=lifecycle.STAGE_PRELIMINARY),
                name="unique_preliminary_task_per_submission",
            ),
            models.CheckConstraint(
                condition=models.Q(is_override=False)
                | models.Q(stage=lifecycle.STAGE_REVIEW),
                name="override_is_review_stage_only",
            ),
        ]
        indexes = [
            models.Index(fields=("reviewer", "status")),
        ]

    def __str__(self):
        return f"{self.reviewer} {self.get_stage_display()} {self.submission}"

    @property
    def is_preliminary(self):
        return self.stage == self.PRELIMINARY

    @property
    def is_review(self):
        return self.stage == self.REVIEW

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
    def status_label(self):
        """状态按阶段叫：待初审／已初审／待评审／已完成。

        字段只能存一套中性 choices，叫法是这里按 ``(stage, status)`` 取的。
        """
        return lifecycle.TASK_STATUS_LABELS.get(
            (self.stage, self.status), self.get_status_display()
        )

    @property
    def decision_tone(self):
        """结论对应的 chip 语气：通过=ok，需修改=warn。"""
        return "ok" if self.decision == self.APPROVE else "warn"


def preliminary_task_of(submission):
    """这一轮的初审任务，或 ``None``。

    Rounds created before the 初审 stage existed have none, so every caller has
    to cope with the absence. The row is read fresh instead of through
    ``submission.tasks``: it is mutated in place — it gets a verdict, a super
    reviewer releases it, an administrator swaps its holder — so a cached copy
    goes stale in exactly the places where it decides something.
    """
    if submission is None or submission.pk is None:
        return None
    return submission.tasks.filter(stage=ReviewTask.PRELIMINARY).first()


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
    source_task = models.ForeignKey(
        ReviewTask,
        on_delete=models.PROTECT,
        related_name="archived_proposals",
        verbose_name="来源任务",
    )
    file = models.FileField(
        "批注版项目书",
        upload_to=upload_archived_proposal,
        storage=private_storage,
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
                fields=("source_task",),
                name="unique_archived_proposal_task",
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
    # 成员中心用 ModelForm 的默认标签渲染这一栏，所以这个 verbose_name 是前台文案。
    reason = models.TextField(_("事由"), blank=True)
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
