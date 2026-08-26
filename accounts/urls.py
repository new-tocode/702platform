from django.urls import path

from . import views


app_name = "accounts"

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", views.PlatformLoginView.as_view(), name="login"),
    path("logout/", views.PlatformLogoutView.as_view(), name="logout"),
    path("member/", views.member_home, name="member_home"),
    path("member/profile/", views.profile, name="profile"),
    path("member/password/", views.PasswordChangeView.as_view(), name="password_change"),
]
