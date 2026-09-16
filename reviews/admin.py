"""Admin oversight for project submissions, review tasks, archives and leaves.

The review records themselves are read-only: they are the durable trace of what
happened. Three models are exceptions, all because they are settings rather than
records —

* ``ReviewerLeave``: the two time fields are editable straight from the
  changelist, because shifting a reviewer's recovery time earlier or later is
  the whole administrative action.
* ``ReviewTask`` and ``ReviewTask``: the holder may be swapped
  while the task is still pending on a round that has not moved past it, and
  only then. The write goes through the matching service so the eligibility
  rules and the audit trail hold.
"""

from django.contrib import admin, messages

from core.audit import record_audit

from . import lifecycle
from .forms import AdminReassignTaskForm
from .models import (
    ArchivedProposal,
    ReviewTask,
    ProjectSubmission,
    ReviewerLeave,
    preliminary_task_of,
)
from .services import ReviewError, reassign_task


@admin.register(ProjectSubmission)
class ProjectSubmissionAdmin(admin.ModelAdmin):
    list_display = (
        "group",
        "round",
        "review_type",
        "status",
        "submitted_by",
        "submitted_at",
        "decided_at",
    )
    list_filter = ("status", "review_type", "submitted_at")
    search_fields = ("group__name", "submitted_by__username")
    list_select_related = ("group", "submitted_by")
    readonly_fields = (
        "group",
        "round",
        "review_type",
        "message",
        "status",
        "submitted_by",
        "submitted_at",
        "decided_at",
    )
    date_hierarchy = "submitted_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_deleted_objects(self, objs, request):
        """Let a round be deleted together with its review tasks.

        ``ReviewTaskAdmin`` and ``ReviewTaskAdmin`` both refuse to
        delete a single task on purpose — that would silently change what the
        round needs. Django's cascade check, however, asks those same admins
        about the tasks a round deletion would carry away, which used to make the
        round undeletable. The waiver is deliberate: the unit of deletion is the
        whole round, and the per-task guards keep their own lock.
        """
        to_delete, model_count, perms_needed, protected = super().get_deleted_objects(
            objs, request
        )
        # perms_needed holds verbose names; 评审任务 is the only one waived here.
        perms_needed.discard(ReviewTask._meta.verbose_name)
        return to_delete, model_count, perms_needed, protected

    @staticmethod
    def _deletion_detail(submission):
        """What to keep in the audit log, gathered before the row disappears."""
        return {
            "submission_id": submission.pk,
            "group_id": submission.group_id,
            "round": submission.round,
            "review_type": submission.review_type,
            "status": submission.status,
            "tasks": submission.tasks.count(),
            "preliminary": 1 if preliminary_task_of(submission) else 0,
        }

    def delete_model(self, request, obj):
        detail = self._deletion_detail(obj)
        super().delete_model(request, obj)
        # target=None: the object is gone, so every identifier lives in detail.
        record_audit(
            action="reviews.submission.delete",
            user=request.user,
            target=None,
            detail=detail,
            request=request,
        )

    def delete_queryset(self, request, queryset):
        details = [self._deletion_detail(obj) for obj in queryset]
        super().delete_queryset(request, queryset)
        record_audit(
            action="reviews.submission.delete",
            user=request.user,
            target=None,
            detail={"submissions": details},
            request=request,
        )


@admin.register(ReviewTask)
class ReviewTaskAdmin(admin.ModelAdmin):
    """只读，唯一的例外是把一张还没交的任务卡换个人。

    A verdict is a record of who decided what: once it exists, the holder of that
    row is never editable. While a task is still pending on a round that has not
    moved past its stage, though, the holder may be swapped — the only way to
    recover a round whose 初审人／评审人 has gone quiet, or turns out to have a
    conflict of interest, and would otherwise sit at 初审中／评审中 forever.

    两道关共用这一屏（合并任务表之前是两个几乎逐字相同的类）：差别只有措辞与
    候选资格，都按 ``lifecycle.STAGES`` 生成。
    """

    list_display = (
        "submission",
        "stage",
        "reviewer",
        "status_label",
        "decision",
        "annotated_file",
        "assigned_at",
        "completed_at",
    )
    list_filter = ("stage", "status", "decision", "assigned_at")
    search_fields = (
        "submission__group__name",
        "reviewer__username",
        "reviewer__profile__full_name",
    )
    list_select_related = ("submission__group", "reviewer")
    readonly_fields = (
        "submission",
        "stage",
        "reviewer",
        "status",
        "decision",
        "comment",
        "annotated_file",
        "is_override",
        "assigned_at",
        "completed_at",
    )

    @admin.display(description="状态")
    def status_label(self, obj):
        """状态按阶段叫（待初审／待评审……）：字段只存中性的取值。"""
        return obj.status_label

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        # 删一条任务会悄悄改变这一轮需要几人／有没有初审：名单保持完整，换人走
        # 详情页。（整轮可以删——见 ProjectSubmissionAdmin.get_deleted_objects。）
        return False

    def _reassignment_allowed(self, request, obj=None):
        """Whether this task may be swapped to another holder, by this user, now.

        Two conditions, both required: the row is still swappable (pending, and
        its round has not moved past its stage) *and* the administrator holds the
        model's change permission. The state check must not replace the ordinary
        permission check — ``view_reviewtask`` alone must not buy a write — and
        it is also what decides whether the change page renders an editable
        holder select at all.
        """
        return bool(
            obj is not None
            and obj.pk is not None
            and obj.status == ReviewTask.PENDING
            and lifecycle.stage_is_open(obj.submission, obj.stage)
        ) and super().has_change_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        # When this is False Django serves the page read-only, which is what
        # every record other than a swappable one should be.
        return self._reassignment_allowed(request, obj)

    def get_readonly_fields(self, request, obj=None):
        if self._reassignment_allowed(request, obj):
            return tuple(f for f in self.readonly_fields if f != "reviewer")
        return self.readonly_fields

    def get_form(self, request, obj=None, change=False, **kwargs):
        if self._reassignment_allowed(request, obj):
            kwargs["form"] = AdminReassignTaskForm
        return super().get_form(request, obj, change=change, **kwargs)

    def save_model(self, request, obj, form, change):
        """Route the swap through the service instead of saving the row.

        The default implementation calls obj.save(), which would write the new
        holder with no eligibility check and no audit entry. Note that Django has
        already applied the submitted holder to ``obj`` in memory;
        ``reassign_task`` re-reads the row itself, so it still sees the holder
        being replaced.
        """
        new_reviewer = form.cleaned_data.get("reviewer")
        if new_reviewer is None:
            # Django already refuses the POST for a task that may not be swapped
            # (has_change_permission is False there), so this is belt-and-braces
            # against another entry point reaching save_model with a plain form.
            return
        try:
            reassign_task(
                task=obj,
                new_reviewer=new_reviewer,
                actor=request.user,
                request=request,
            )
        except ReviewError as exc:
            self.message_user(request, str(exc), messages.ERROR)
        else:
            label = lifecycle.STAGES[obj.stage].holder_label
            self.message_user(request, f"已更换{label}。", messages.SUCCESS)


@admin.register(ArchivedProposal)
class ArchivedProposalAdmin(admin.ModelAdmin):
    list_display = (
        "group",
        "submission",
        "file",
        "archived_at",
    )
    list_filter = ("archived_at",)
    search_fields = ("group__name",)
    list_select_related = ("group", "submission")
    readonly_fields = (
        "group",
        "submission",
        "source_task",
        "file",
        "archived_at",
    )
    date_hierarchy = "archived_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ReviewerLeave)
class ReviewerLeaveAdmin(admin.ModelAdmin):
    list_display = (
        "reviewer",
        "starts_at",
        "ends_at",
        "state_label",
        "reason",
        "created_by",
        "updated_at",
    )
    # The whole point of this screen: move a reviewer's recovery time without
    # opening each row.
    list_editable = ("starts_at", "ends_at")
    list_filter = ("starts_at", "ends_at")
    search_fields = ("reviewer__username", "reviewer__profile__full_name", "reason")
    list_select_related = ("reviewer", "created_by")
    readonly_fields = ("created_by", "created_at", "updated_at")
    date_hierarchy = "starts_at"
    ordering = ("-starts_at", "-id")

    @admin.display(description="当前状态")
    def state_label(self, obj):
        return obj.state_label

    def save_model(self, request, obj, form, change):
        if obj.created_by_id is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
        # Django's own LogEntry also records the edit; this keeps the platform's
        # audit trail complete for changes made straight from the changelist.
        record_audit(
            action="reviews.leave.admin_save",
            user=request.user,
            target=obj,
            detail={
                "reviewer_id": obj.reviewer_id,
                "created": not change,
                "ends_at": obj.ends_at.isoformat() if obj.ends_at else "",
            },
            request=request,
        )
