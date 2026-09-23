from django.urls import path

from . import views


app_name = "accounts"

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", views.PlatformLoginView.as_view(), name="login"),
    path("logout/", views.PlatformLogoutView.as_view(), name="logout"),
    path("member/", views.member_home, name="member_home"),
    path("member/profile/", views.profile, name="profile"),
    path("member/profile/avatar/", views.avatar_update, name="avatar_update"),
    path("member/profile/avatar/delete/", views.avatar_delete, name="avatar_delete"),
    path("member/password/", views.PasswordChangeView.as_view(), name="password_change"),
]
