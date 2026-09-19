from django.urls import path

from . import views


app_name = "projects"

urlpatterns = [
    path("", views.group_list, name="group_list"),
    path("create/", views.group_create_request, name="group_create_request"),
    path(
        "create/requests/<int:req_pk>/<str:action>/",
        views.group_create_decide,
        name="group_create_decide",
    ),
    path("<int:pk>/", views.group_detail, name="group_detail"),
    path("<int:pk>/apply/", views.group_apply, name="group_apply"),
    path("<int:pk>/proposal/", views.group_proposal_download, name="group_proposal_download"),
    path("<int:pk>/manage/", views.group_manage, name="group_manage"),
    path(
        "<int:pk>/manage/proposal/",
        views.group_proposal_update,
        name="group_proposal_update",
    ),
    path(
        "<int:pk>/manage/submit/",
        views.group_submit_review,
        name="group_submit_review",
    ),
    path(
        "<int:pk>/manage/requests/<int:req_pk>/<str:action>/",
        views.group_request_decide,
        name="group_request_decide",
    ),
    path(
        "<int:pk>/manage/members/<int:user_pk>/remove/",
        views.group_member_remove,
        name="group_member_remove",
    ),
]
