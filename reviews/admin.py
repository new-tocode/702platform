"""Read-only admin oversight for project submissions, review tasks and archives."""

from django.contrib import admin

from .models import ArchivedProposal, ProjectSubmission, ReviewAssignment


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
