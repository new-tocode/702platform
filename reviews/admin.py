"""Admin oversight for project submissions, review tasks, archives and leaves.

The review records themselves are read-only: they are the durable trace of what
happened. ``ReviewerLeave`` is the exception — it is an operational setting, and
the two time fields are editable straight from the changelist because shifting a
reviewer's recovery time earlier or later is the whole administrative action.
"""

from django.contrib import admin

from core.audit import record_audit

from .models import (
    ArchivedProposal,
    ProjectSubmission,
    ReviewAssignment,
    ReviewerLeave,
)


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

    def has_change_permission(self, request, obj=None):
        return False


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
