from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils.translation import gettext_lazy as _

from core.audit import record_audit

from .models import Board, Comment, Post
from .permissions import (
    can_comment,
    can_create_board,
    can_create_post,
    can_delete_board,
    can_delete_post,
    can_edit_post,
    can_pin_post,
    is_member,
)
from .validators import clean_board_name


class DiscussionError(Exception):
    """A discussion action violates a business rule."""


class DiscussionNotFound(DiscussionError):
    """The requested board or post no longer exists."""


class BoardNameTaken(DiscussionError):
    """A board already uses this name."""


class BoardNotEmpty(DiscussionError):
    """A board with posts cannot be deleted."""


def _require_member(actor):
    if not is_member(actor):
        raise PermissionDenied


def _require_board_creation(actor):
    if not can_create_board(actor):
        raise PermissionDenied


def _board_for_update(board_id):
    try:
        return Board.objects.select_for_update().get(pk=board_id)
    except Board.DoesNotExist as exc:
        raise DiscussionNotFound from exc


def _post_for_update(post_id):
    try:
        return Post.objects.select_for_update().get(pk=post_id)
    except Post.DoesNotExist as exc:
        raise DiscussionNotFound from exc


def create_board(*, name, actor, request=None):
    _require_board_creation(actor)
    try:
        name = clean_board_name(name)
    except ValidationError as exc:
        raise DiscussionError(exc.messages[0]) from exc

    try:
        with transaction.atomic():
            board = Board.objects.create(name=name, created_by=actor)
    except IntegrityError as exc:
        raise BoardNameTaken(_("已有同名板块。")) from exc

    record_audit(
        action="discussion.board.create",
        user=actor,
        target=board,
        detail={"name": name},
        request=request,
    )
    return board


def delete_board(*, board_id, actor, request=None):
    if not can_delete_board(actor):
        raise PermissionDenied

    with transaction.atomic():
        board = _board_for_update(board_id)
        if board.posts.exists():
            raise BoardNotEmpty(_("请先删除板块中的所有帖子，再删除板块。"))
        record_audit(
            action="discussion.board.delete",
            user=actor,
            target=board,
            detail={"name": board.name},
            request=request,
        )
        board.delete()


def create_post(*, board_id, title, content, actor, request=None):
    if not can_create_post(actor):
        raise PermissionDenied
    title = title.strip()
    content = content.strip()
    if not title or not content:
        raise DiscussionError(_("帖子标题和正文不能为空。"))

    with transaction.atomic():
        board = _board_for_update(board_id)
        post = Post.objects.create(
            board=board,
            author=actor,
            title=title,
            content=content,
        )

    record_audit(
        action="discussion.post.create",
        user=actor,
        target=post,
        detail={"board_id": board.pk},
        request=request,
    )
    return post


def update_post(*, post_id, title, content, actor, request=None):
    _require_member(actor)
    title = title.strip()
    content = content.strip()
    if not title or not content:
        raise DiscussionError(_("帖子标题和正文不能为空。"))

    with transaction.atomic():
        post = _post_for_update(post_id)
        if not can_edit_post(actor, post):
            raise PermissionDenied
        post.title = title
        post.content = content
        post.save(update_fields=["title", "content", "updated_at"])

    record_audit(
        action="discussion.post.update",
        user=actor,
        target=post,
        detail={"board_id": post.board_id},
        request=request,
    )
    return post


def delete_post(*, post_id, actor, request=None):
    _require_member(actor)
    with transaction.atomic():
        post = _post_for_update(post_id)
        if not can_delete_post(actor, post):
            raise PermissionDenied
        detail = {
            "post_id": post.pk,
            "board_id": post.board_id,
            "author_id": post.author_id,
            "comment_count": post.comments.count(),
        }
        record_audit(
            action="discussion.post.delete",
            user=actor,
            target=post,
            detail=detail,
            request=request,
        )
        post.delete()


def set_post_pinned(*, post_id, is_pinned, actor, request=None):
    if not can_pin_post(actor):
        raise PermissionDenied

    with transaction.atomic():
        post = _post_for_update(post_id)
        post.is_pinned = bool(is_pinned)
        post.save(update_fields=["is_pinned", "updated_at"])

    record_audit(
        action="discussion.post.pin" if post.is_pinned else "discussion.post.unpin",
        user=actor,
        target=post,
        detail={"board_id": post.board_id},
        request=request,
    )
    return post


def create_comment(*, post_id, content, actor, request=None):
    if not can_comment(actor):
        raise PermissionDenied
    content = content.strip()
    if not content:
        raise DiscussionError(_("评论内容不能为空。"))

    with transaction.atomic():
        post = _post_for_update(post_id)
        comment = Comment.objects.create(
            post=post,
            author=actor,
            content=content,
        )

    record_audit(
        action="discussion.comment.create",
        user=actor,
        target=comment,
        detail={"post_id": post.pk, "board_id": post.board_id},
        request=request,
    )
    return comment
