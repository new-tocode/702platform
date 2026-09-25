"""Project groups, their leader/member relationships, and their advisors."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models

from core.storage import neutral_upload_to, private_storage

from .validators import validate_proposal_file


class ProjectGroup(models.Model):
    name = models.CharField("组名", max_length=200)
    leader = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="led_project_groups",
        verbose_name="项目组联系人",
    )
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="project_groups",
        blank=True,
        verbose_name="成员",
    )
    description = models.TextField("简介", blank=True)
    college = models.CharField("学院", max_length=128, blank=True)
    proposal = models.FileField(
        "项目书",
        # 落盘名与用户填的名字脱钩：原名常带组名与人名（「项目书 终版-张三.docx」
        # 是典型叫法），而文件名会跟着文件走进备份、走进运维的 ls、走进下载头。
        # 存放在私有根下，取件走 projects.views.group_proposal_download。
        upload_to=neutral_upload_to("project_proposals"),
        storage=private_storage,
        blank=True,
        validators=[validate_proposal_file],
        help_text="支持 doc、docx、pdf；由项目组联系人维护，用于提交同行评审。",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "项目组"
        verbose_name_plural = "项目组"
        ordering = ("name", "id")

    def __str__(self):
        return self.name

    @property
    def advisor_names(self):
        """Advisor names in slot order, joined for display; empty when none.

        Relies on the caller prefetching ``advisors`` (the group list and detail
        views both do) — without that this costs one query per group.
        """
        return "、".join(advisor.name for advisor in self.advisors.all())

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # A group's leader is always a member of that group. This keeps the
        # registration form and all membership displays internally consistent.
        if self.leader_id:
            self.members.add(self.leader_id)


#: Advisors one project group may have, and the only place the cap is written
#: down — the model's two constraints and the group forms both derive from it.
MAX_ADVISORS_PER_GROUP = 3

#: Slots an advisor can occupy; ``第 1 位`` … ``第 3 位``.
ADVISOR_SLOT_CHOICES = tuple(
    (slot, f"第 {slot + 1} 位") for slot in range(MAX_ADVISORS_PER_GROUP)
)


class ProjectAdvisor(models.Model):
    """A supervising teacher of a project group.

    Kept in its own table rather than as fixed columns on :class:`ProjectGroup`
    so a group carries anywhere from zero to :data:`MAX_ADVISORS_PER_GROUP`
    advisors with no empty gaps. Advisors are plain names — the platform has no
    teacher accounts to point at.
    """

    group = models.ForeignKey(
        ProjectGroup,
        on_delete=models.CASCADE,
        related_name="advisors",
        verbose_name="项目组",
    )
    name = models.CharField("指导老师", max_length=128)
    sort_order = models.PositiveSmallIntegerField(
        "顺序",
        choices=ADVISOR_SLOT_CHOICES,
        default=0,
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "指导老师"
        verbose_name_plural = "指导老师"
        ordering = ("sort_order", "id")
        constraints = [
            # 「最多 3 位」落在数据库层：槽位只有 0/1/2，且同组内不重复，
            # 两条合起来即「每组至多 3 条」。
            models.UniqueConstraint(
                fields=("group", "sort_order"),
                name="unique_project_advisor_slot",
            ),
            models.CheckConstraint(
                condition=models.Q(sort_order__lt=MAX_ADVISORS_PER_GROUP),
                name="project_advisor_slot_within_three",
            ),
        ]

    def __str__(self):
        return f"{self.group.name} · {self.name}"


class GroupJoinRequest(models.Model):
    """A membership application awaiting review by the group's contact."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    STATUS_CHOICES = (
        (PENDING, "待审核"),
        (APPROVED, "已通过"),
        (REJECTED, "已拒绝"),
    )

    group = models.ForeignKey(
        ProjectGroup,
        on_delete=models.PROTECT,
        related_name="join_requests",
        verbose_name="项目组",
    )
    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="group_join_requests",
        verbose_name="申请人",
    )
    message = models.TextField("申请理由", blank=True)
    status = models.CharField(
        "状态",
        max_length=16,
        choices=STATUS_CHOICES,
        default=PENDING,
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="decided_group_join_requests",
        verbose_name="处理人",
    )
    decided_at = models.DateTimeField("处理时间", null=True, blank=True)
    created_at = models.DateTimeField("提交时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "入组申请"
        verbose_name_plural = "入组申请"
        ordering = ("-created_at", "-id")
        constraints = [
            # At most one pending application per group and applicant; a
            # rejected applicant may apply again later.
            models.UniqueConstraint(
                fields=("group", "applicant"),
                condition=models.Q(status="pending"),
                name="unique_pending_group_join_request",
            ),
        ]
        indexes = [
            models.Index(fields=("group", "status")),
            models.Index(fields=("applicant", "status")),
        ]

    def __str__(self):
        return f"{self.applicant} → {self.group}（{self.get_status_display()}）"


class GroupCreateRequest(models.Model):
    """An application to found a new project group, decided by any administrator.

    Any logged-in member may apply, whatever their current role; the applicant
    becomes the new group's contact. Reviewers are the administrators, and one
    approval settles it for all of them — the rest of the queue drops the entry.
    """

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    STATUS_CHOICES = (
        (PENDING, "待审核"),
        (APPROVED, "已通过"),
        (REJECTED, "已拒绝"),
    )

    name = models.CharField("项目组名称", max_length=200)
    description = models.TextField("项目组描述")
    college = models.CharField("学院", max_length=128, blank=True)
    # 指导老师在申请上先占三个固定槽位（与 MAX_ADVISORS_PER_GROUP 一一对应），
    # 审核通过时转成 ProjectAdvisor 行。申请记录不是项目组，不另建一张子表。
    advisor_1 = models.CharField("指导老师 1", max_length=128, blank=True)
    advisor_2 = models.CharField("指导老师 2", max_length=128, blank=True)
    advisor_3 = models.CharField("指导老师 3", max_length=128, blank=True)
    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="group_create_requests",
        verbose_name="申请人",
    )
    status = models.CharField(
        "状态",
        max_length=16,
        choices=STATUS_CHOICES,
        default=PENDING,
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="decided_group_create_requests",
        verbose_name="处理人",
    )
    decided_at = models.DateTimeField("处理时间", null=True, blank=True)
    created_group = models.OneToOneField(
        ProjectGroup,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="create_request",
        verbose_name="创建的项目组",
    )
    created_at = models.DateTimeField("提交时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "创建项目组申请"
        verbose_name_plural = "创建项目组申请"
        ordering = ("-created_at", "-id")
        constraints = [
            # 同一申请人同时只有一条待审申请；被拒绝后可以重新申请。
            models.UniqueConstraint(
                fields=("applicant",),
                condition=models.Q(status="pending"),
                name="unique_pending_group_create_request",
            ),
        ]
        indexes = [
            models.Index(fields=("status", "created_at")),
        ]

    def __str__(self):
        return f"{self.applicant} → {self.name}（{self.get_status_display()}）"

    @property
    def filled_advisor_names(self):
        """已填写的指导老师姓名**列表**，按槽位顺序；空槽位不占位。

        刻意不叫 ``advisor_names``：那是 :class:`ProjectGroup` 上拼好的展示串，
        这边是供服务层逐位建行的列表，同名会让两处读起来像同一件东西。
        """
        return [
            name.strip()
            for name in (self.advisor_1, self.advisor_2, self.advisor_3)
            if name.strip()
        ]


class ProjectContact(get_user_model()):
    """Read-only proxy giving administrators a single list of all contacts.

    Contact identity is derived from ``ProjectGroup.leader``; this proxy stores
    nothing and only exists so the admin can browse every contact at a glance.
    """

    class Meta:
        proxy = True
        verbose_name = "项目组联系人"
        verbose_name_plural = "项目组联系人"


class ProjectMember(get_user_model()):
    """Read-only proxy giving administrators a single list of all members.

    Membership is derived from ``ProjectGroup.members``; like ``ProjectContact``
    this stores nothing. Both are 名册 for viewing only —— 成员关系只能由业务
    动作产生（入组审批、建组、联系人转让），后台不提供分配入口。
    """

    class Meta:
        proxy = True
        verbose_name = "项目组成员"
        verbose_name_plural = "项目组成员"
