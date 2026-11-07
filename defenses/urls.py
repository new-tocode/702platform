from django.urls import path

from . import views


app_name = "defenses"

urlpatterns = [
    # 排期表：成员中心的「线下答辩」入口进来，所有登录成员可看。
    path("", views.schedule, name="schedule"),
    # 发起入口在项目组详情页，带上这个组。
    path("new/<int:group_pk>/", views.request_create, name="request_create"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/edit/", views.request_edit, name="request_edit"),
    path("<int:pk>/comments/", views.comment_create, name="comment_create"),
    path("<int:pk>/close/", views.request_close, name="request_close"),
]
