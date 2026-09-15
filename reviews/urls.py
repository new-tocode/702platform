from django.urls import path

from . import views


app_name = "reviews"

urlpatterns = [
    path("", views.review_queue, name="queue"),
    path("leave/", views.set_leave, name="set_leave"),
    path("leave/cancel/", views.cancel_leave, name="cancel_leave"),
    path("<int:pk>/complete/", views.complete_assignment, name="complete"),
    path("override/<int:pk>/", views.override_submission, name="override"),
    path("<int:pk>/annotated/", views.annotated_file_download, name="annotated"),
    path(
        "archive/<int:pk>/download/",
        views.archived_proposal_download,
        name="archive_download",
    ),
]
