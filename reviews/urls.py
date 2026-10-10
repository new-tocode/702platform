from django.urls import path

from . import views


app_name = "reviews"

urlpatterns = [
    path("", views.review_queue, name="queue"),
    # 接单开关：一道关一个（stage=preliminary|review），只给自己开。
    path("availability/", views.set_availability, name="set_availability"),
    # 两条路由指向同一个视图：谁的门槛与哪张表单，由任务自己的 stage 决定。
    # 路径与 name 保持合并前的样子，历史链接与书签都不受影响。
    path(
        "preliminary/<int:pk>/complete/",
        views.complete_task,
        name="preliminary_complete",
    ),
    path("<int:pk>/complete/", views.complete_task, name="complete"),
    path("override/<int:pk>/", views.override_submission, name="override"),
    path("<int:pk>/annotated/", views.annotated_file_download, name="annotated"),
    path(
        "archive/<int:pk>/download/",
        views.archived_proposal_download,
        name="archive_download",
    ),
]
