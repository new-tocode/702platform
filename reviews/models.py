"""Journal-style peer review of a project group's materials.

Each :class:`ProjectSubmission` is one review round of a project group's
materials. A round starts in the hands of one :class:`ReviewTask` (初审):
that single reviewer passes the materials on — which is when the round draws the
reviewers its type calls for — or sends it back for revision. From then on
:class:`ReviewTask` records one reviewer's verdict, and a submission is
approved only when every assignment is complete and every verdict approves.

The materials themselves are **not** copied here: reviewers download the
project group's current materials (``ProjectGroup.materials``) from the group
detail page, so there is a single stored file per group.

How many reviewers a round needs depends on the type the submitter picks
(``REVIEWER_QUOTA``): competition rounds need three, an innovation project needs
one at kick-off and two at mid-term/final. A reviewer may attach a reply archive
along with the verdict; once the round is approved those replies are archived as
:class:`ArchivedReply` records.

The ``review_type`` labels are **platform-local tags** and deliberately have no
foreign key to ``competitions.Competition``.
"""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.hashing import FileDigestMixin
from core.storage import neutral_upload_to, private_storage
from projects.models import ProjectGroup

from . import lifecycle
from .validators import REPLY_HELP_TEXT, validate_reply_file


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


#: 评审人的评审回复与归档件：落盘名一律 uuid。
#:
#: 匿名是评审的硬约束，而文件名是最容易漏的一处——``zhangsan-评审回复.zip`` 这样的
#: 名字会把评审人直接写进存储层，再跟着备份与运维的 ls 一路扩散出去。命名口径与
#: 其他受保护上传件统一到 core.storage，只在目录前缀上区分（前缀是存储内部路径，
#: 不对外，也不随字段改名而动——改了会让已有文件与新文件分居两处）。
upload_review_reply = neutral_upload_to("review_annotations")
upload_archived_reply = neutral_upload_to("review_archives")

#: 这两个名字是 ``upload_to`` 的历史写法，**历史迁移按名引用**（``reviews/0002``、
#: ``0006``、``0007`` 里是 ``reviews.models.upload_annotated_proposal`` 这样的字面量），
#: Django 加载迁移时会来取，删掉它们 manage.py 都起不来。值就是上面那两个，
#: ``NeutralUploadTo`` 按前缀判等，所以留别名不会让 autodetector 看出差别。
upload_annotated_proposal = upload_review_reply
upload_archived_proposal = upload_archived_reply


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
    message = models.TextField("提交说明", max_length=5000, blank=True)
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
        verbose_name = "项目资料送审"
        verbose_name_plural = "项目资料送审"
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


class ReviewTask(FileDigestMixin, models.Model):
    """一轮送审里的一张任务卡：初审一道关，评审一个评审团。

    两道关的任务**形状相同**——同一个持有人概念、同一个状态机、同一对结论、同样的
    改派与释放规则——所以只有一张表，``stage`` 说明这是哪一道。差异只有三处，都由
    约束或 :data:`reviews.lifecycle.STAGES` 表达：

    * 一轮恰好一条初审（``unique_preliminary_task_per_submission``）；
    * 评审回复只有评审阶段会填（初审给的是理由，不是稿子）；
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

    #: 评审人随结论附上的评审回复；下载页上附出它的 SHA-256 供人比对。
    digest_field = "reply_file"

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
    comment = models.TextField("意见", max_length=5000, blank=True)
    is_override = models.BooleanField(
        "超级评审决定",
        default=False,
        help_text="该行来自超级评审的一票决定：本轮结论由它单独敲定，等待中的任务随即被释放。",
    )
    reply_file = models.FileField(
        "评审回复",
        upload_to=upload_review_reply,
        storage=private_storage,
        blank=True,
        validators=[validate_reply_file],
        help_text=REPLY_HELP_TEXT,
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


class ArchivedReply(FileDigestMixin, models.Model):
    """An approved round's reply archive, kept as the group's record.

    One row per reviewer who actually attached a reply — reviewers who answered
    with text only produce no row, and the project materials are never
    duplicated here. Rows are written once when a round turns ``approved`` and
    are immutable afterwards.
    """

    #: 归档件是评审回复在通过那一刻的副本，指纹因此与源任务上的那份一致——
    #: 两边对不上就说明归档之后被动过。
    digest_field = "file"

    group = models.ForeignKey(
        ProjectGroup,
        on_delete=models.PROTECT,
        related_name="archived_replies",
        verbose_name="项目组",
    )
    submission = models.ForeignKey(
        ProjectSubmission,
        on_delete=models.PROTECT,
        related_name="archived_replies",
        verbose_name="送审",
    )
    source_task = models.ForeignKey(
        ReviewTask,
        on_delete=models.PROTECT,
        related_name="archived_replies",
        verbose_name="来源任务",
    )
    file = models.FileField(
        "评审回复",
        upload_to=upload_archived_reply,
        storage=private_storage,
    )
    archived_at = models.DateTimeField("归档时间", auto_now_add=True)

    class Meta:
        verbose_name = "评审回复归档"
        verbose_name_plural = "评审回复归档"
        ordering = ("-archived_at", "-id")
        constraints = [
            # Archiving runs inside the verdict aggregation, which may be
            # retried; one archive per source assignment keeps it idempotent.
            models.UniqueConstraint(
                fields=("source_task",),
                name="unique_archived_reply_task",
            ),
        ]
        indexes = [
            models.Index(fields=("group", "-archived_at")),
        ]

    def __str__(self):
        return f"{self.group} 第 {self.submission.round} 轮的评审回复"
