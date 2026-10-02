from django.urls import path

from . import views


app_name = "member_notices"

urlpatterns = [
    path("", views.internal_list, name="internal_list"),
    # 放在 <int:pk> 之前：它不是一条通知的编号，别让路由先按编号去匹配。
    path("read-all/", views.mark_all_read, name="mark_all_read"),
    # 事件消息的中转：标已读后跳到帖子/项目组等目标页。
    path("message/<int:pk>/go/", views.message_go, name="message_go"),
    path("<int:pk>/", views.internal_detail, name="internal_detail"),
]
