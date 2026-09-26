from django.urls import path

from . import file_views, views


app_name = "accounts"

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", views.PlatformLoginView.as_view(), name="login"),
    path("logout/", views.PlatformLogoutView.as_view(), name="logout"),
    path("member/", views.member_home, name="member_home"),
    path("member/profile/", views.profile, name="profile"),
    path(
        "member/profile/<int:user_id>/",
        views.member_profile_readonly,
        name="member_profile",
    ),
    # 受保护文件的取件口（见 accounts/file_views.py）：头像与图册不在公开的
    # /media/ 下，只能从这里出去。
    path(
        "member/avatar/<int:user_id>/",
        file_views.avatar_file,
        name="avatar_file",
    ),
    path(
        "member/gallery/<int:pk>/file/",
        file_views.gallery_file,
        name="gallery_file",
    ),
    path("member/profile/avatar/", views.avatar_update, name="avatar_update"),
    path("member/profile/avatar/delete/", views.avatar_delete, name="avatar_delete"),
    path("member/profile/gallery/", views.gallery_upload, name="gallery_upload"),
    path(
        "member/profile/gallery/<int:pk>/move/",
        views.gallery_image_move,
        name="gallery_image_move",
    ),
    path(
        "member/profile/gallery/<int:pk>/layout/",
        views.gallery_image_layout,
        name="gallery_image_layout",
    ),
    path(
        "member/profile/gallery/<int:pk>/delete/",
        views.gallery_image_delete,
        name="gallery_image_delete",
    ),
    path("member/password/", views.PasswordChangeView.as_view(), name="password_change"),
]
