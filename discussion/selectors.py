from django.contrib.auth import get_user_model
from django.db.models import Prefetch

from .models import Board, Comment, Post


User = get_user_model()


def board_list():
    return Board.objects.order_by("name", "pk")


def posts_for_board(board):
    comments = Comment.objects.select_related("author", "author__profile")
    return (
        Post.objects.filter(board=board)
        .select_related("author", "author__profile")
        .prefetch_related(Prefetch("comments", queryset=comments))
    )


def member_directory(*, name_query=""):
    members = (
        User.objects.filter(is_active=True)
        .select_related("profile")
        .order_by("profile__full_name", "username", "pk")
    )
    name_query = name_query.strip()
    if name_query:
        members = members.filter(profile__full_name__icontains=name_query)
    return members
