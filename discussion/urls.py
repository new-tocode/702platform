from django.urls import path

from . import views


app_name = "discussion"

urlpatterns = [
    path("", views.space, name="space"),
    path("boards/<int:board_id>/", views.board, name="board"),
    path("boards/<int:board_id>/posts/new/", views.post_new, name="post_new"),
    path("boards/<int:board_id>/delete/", views.board_delete, name="board_delete"),
    path("boards/create/", views.board_create, name="board_create"),
    path("posts/<int:post_id>/edit/", views.post_edit, name="post_edit"),
    path("posts/<int:post_id>/delete/", views.post_delete, name="post_delete"),
    path("posts/<int:post_id>/pin/", views.post_pin, name="post_pin"),
    path("posts/<int:post_id>/comments/", views.comment_create, name="comment_create"),
]
