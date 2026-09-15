"""Admin oversight for project submissions, review tasks, archives and leaves.

The review records themselves are read-only: they are the durable trace of what
happened. Two models are exceptions, both because they are settings rather than
records —

* ``ReviewerLeave``: the two time fields are editable straight from the
  changelist, because shifting a reviewer's recovery time earlier or later is
  the whole administrative action.
* ``ReviewAssignment``: the reviewer may be swapped while the task is still
  pending on an undecided round, and only then. The write goes through
  ``reassign_reviewer`` so the eligibility rules and the audit trail hold.
"""

from django.contrib import admin, messages

from core.audit import record_audit

from .forms import AdminReassignReviewerForm
from .models import (
    ArchivedProposal,
    ProjectSubmission,
    ReviewAssignment,
    ReviewerLeave,
)
from .services import ReviewError, reassign_reviewer


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


@admin.register(ReviewAssignment)
class ReviewAssignmentAdmin(admin.ModelAdmin):
    """Read-only, except for handing a still-pending task to another reviewer.

    A verdict is a record of who decided what: once it exists, the reviewer of
    that row is never editable, in line with the other review models. While a
    task is still pending on an undecided round, though, the reviewer can be
    swapped — this is the only way to recover a round whose reviewer has gone
    quiet, or turns out to have a conflict of interest, and would otherwise sit
    at 评审中 forever.
    """

    list_display = (
        "submission",
        "reviewer",
        "status",
        "decision",
        "annotated_file",
        "assigned_at",
        "completed_at",
    )
    list_filter = ("status", "decision", "assigned_at")
    search_fields = (
        "submission__group__name",
        "reviewer__username",
        "reviewer__profile__full_name",
    )
    list_select_related = ("submission__group", "reviewer")
    readonly_fields = (
        "submission",
        "reviewer",
        "status",
        "decision",
        "comment",
        "annotated_file",
        "assigned_at",
        "completed_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        # Deleting a task would silently change how many reviewers the round
        # needs; the roster stays whole and swaps go through the change page.
        return False

    @staticmethod
    def _reassignment_allowed(obj):
        """A swap is sound only while this task and its round are both still open."""
        return bool(
            obj is not None
            and obj.pk is not None
            and obj.status == ReviewAssignment.PENDING
            and obj.submission.status == ProjectSubmission.PENDING
        )

    def has_change_permission(self, request, obj=None):
        # When this is False Django serves the page read-only, which is exactly
        # what every record other than a swappable one should be.
        return self._reassignment_allowed(obj)

    def get_readonly_fields(self, request, obj=None):
        if self._reassignment_allowed(obj):
            return tuple(f for f in self.readonly_fields if f != "reviewer")
        return self.readonly_fields

    def get_form(self, request, obj=None, change=False, **kwargs):
        if self._reassignment_allowed(obj):
            kwargs["form"] = AdminReassignReviewerForm
        return super().get_form(request, obj, change=change, **kwargs)

    def save_model(self, request, obj, form, change):
        """Route the swap through the service instead of saving the row.

        The default implementation calls obj.save(), which would write the new
        reviewer with no eligibility check and no audit entry. Note that Django
        has already applied the submitted reviewer to ``obj`` in memory;
        ``reassign_reviewer`` re-reads the row itself, so it still sees the
        reviewer being replaced.
        """
        new_reviewer = form.cleaned_data.get("reviewer")
        if new_reviewer is None:
            # Django already refuses the POST for a task that may not be swapped
            # (has_change_permission is False there), so this is belt-and-braces
            # against another entry point reaching save_model with a plain form.
            return
        try:
            reassign_reviewer(
                assignment=obj,
                new_reviewer=new_reviewer,
                actor=request.user,
                request=request,
            )
        except ReviewError as exc:
            self.message_user(request, str(exc), messages.ERROR)
        else:
            self.message_user(request, "已更换评审人。", messages.SUCCESS)


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
        "source_assignment",
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
