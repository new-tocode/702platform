from django.contrib.auth import get_user_model
from django.db.models import Prefetch

from .models import Board, Comment, Post, PostImage


User = get_user_model()

#: 一页多少篇帖子；翻页与「这条帖子在第几页」共用这一个数。
POSTS_PER_PAGE = 12


def board_list():
    return Board.objects.order_by("name_zh", "name", "pk")


def posts_for_board(board):
    comments = Comment.objects.alive().select_related("author", "author__profile")
    images = PostImage.objects.order_by("created_at", "pk")
    return (
        Post.objects.filter(board=board)
        .select_related("author", "author__profile")
        .prefetch_related(
            Prefetch("comments", queryset=comments),
            Prefetch("images", queryset=images),
        )
    )


def page_of_post(post):
    """该帖在所属板块列表里的页码（1 起）。

    顺序与 :func:`posts_for_board` 一致（置顶优先、时间倒序）——消息里的「第
    几页」必须和列表观感一致，不然点过去会落到别的页。板块帖子是社团规模，
    数一遍 id 足够。
    """
    ids = list(
        Post.objects.filter(board_id=post.board_id)
        .order_by("-is_pinned", "-created_at", "-pk")
        .values_list("pk", flat=True)
    )
    return ids.index(post.pk) // POSTS_PER_PAGE + 1


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
