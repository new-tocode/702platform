from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils.translation import gettext_lazy as _

from core.audit import record_audit

from .models import Board, Comment, Post, PostImage
from .permissions import (
    can_comment,
    can_create_board,
    can_create_post,
    can_delete_board,
    can_delete_comment,
    can_delete_post,
    can_edit_post,
    can_pin_post,
    is_member,
)
from .validators import (
    POST_IMAGE_LIMIT,
    clean_board_name,
    clean_chinese_board_name,
    validate_post_image,
)


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


def _validated_images(images):
    uploads = list(images or ())
    if len(uploads) > POST_IMAGE_LIMIT:
        raise DiscussionError(_("每篇帖子最多上传 3 张图片。"))
    for uploaded_file in uploads:
        try:
            validate_post_image(uploaded_file)
        except ValidationError as exc:
            raise DiscussionError(exc.messages[0]) from exc
    return uploads


def _store_post_images(*, post, uploads, saved_files):
    for uploaded_file in uploads:
        image = PostImage(post=post, image=uploaded_file)
        try:
            image.save()
        except Exception:
            if image.image and image.image._committed:
                image.image.storage.delete(image.image.name)
            raise
        saved_files.append((image.image.storage, image.image.name))


def _delete_stored_files(files):
    for storage, name in files:
        storage.delete(name)


def create_board(*, name_zh, name, actor, request=None):
    _require_board_creation(actor)
    try:
        name = clean_board_name(name)
    except ValidationError as exc:
        raise DiscussionError(exc.messages[0]) from exc
    try:
        name_zh = clean_chinese_board_name(name_zh)
    except ValidationError as exc:
        raise DiscussionError(exc.messages[0]) from exc

    try:
        with transaction.atomic():
            board = Board.objects.create(
                name_zh=name_zh,
                name=name,
                created_by=actor,
            )
    except IntegrityError as exc:
        raise BoardNameTaken(_("已有同名板块。")) from exc

    record_audit(
        action="discussion.board.create",
        user=actor,
        target=board,
        detail={"name_zh": name_zh, "name": name},
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
            detail={"name_zh": board.name_zh, "name": board.name},
            request=request,
        )
        board.delete()


def create_post(*, board_id, title, content, actor, images=(), request=None):
    if not can_create_post(actor):
        raise PermissionDenied
    title = title.strip()
    content = content.strip()
    if not title or not content:
        raise DiscussionError(_("帖子标题和正文不能为空。"))
    uploads = _validated_images(images)
    saved_files = []

    try:
        with transaction.atomic():
            board = _board_for_update(board_id)
            post = Post.objects.create(
                board=board,
                author=actor,
                title=title,
                content=content,
            )
            _store_post_images(post=post, uploads=uploads, saved_files=saved_files)
    except Exception:
        _delete_stored_files(saved_files)
        raise

    record_audit(
        action="discussion.post.create",
        user=actor,
        target=post,
        detail={"board_id": board.pk, "image_count": len(saved_files)},
        request=request,
    )
    return post


def update_post(
    *,
    post_id,
    title,
    content,
    actor,
    images=(),
    remove_image_ids=(),
    request=None,
):
    _require_member(actor)
    title = title.strip()
    content = content.strip()
    if not title or not content:
        raise DiscussionError(_("帖子标题和正文不能为空。"))
    uploads = _validated_images(images)
    try:
        remove_ids = {int(image_id) for image_id in remove_image_ids}
    except (TypeError, ValueError) as exc:
        raise DiscussionError(_("所选图片无效。")) from exc

    saved_files = []
    files_to_delete = []
    try:
        with transaction.atomic():
            post = _post_for_update(post_id)
            if not can_edit_post(actor, post):
                raise PermissionDenied
            existing_images = list(
                PostImage.objects.select_for_update()
                .filter(post=post)
                .order_by("pk")
            )
            existing_ids = {image.pk for image in existing_images}
            if not remove_ids.issubset(existing_ids):
                raise DiscussionError(_("所选图片不属于这篇帖子。"))
            remaining = len(existing_images) - len(remove_ids)
            if remaining + len(uploads) > POST_IMAGE_LIMIT:
                raise DiscussionError(_("每篇帖子最多保留 3 张图片。"))

            post.title = title
            post.content = content
            post.save(update_fields=["title", "content", "updated_at"])
            for image in existing_images:
                if image.pk in remove_ids:
                    files_to_delete.append((image.image.storage, image.image.name))
                    image.delete()
            _store_post_images(post=post, uploads=uploads, saved_files=saved_files)
    except Exception:
        _delete_stored_files(saved_files)
        raise

    _delete_stored_files(files_to_delete)
    record_audit(
        action="discussion.post.update",
        user=actor,
        target=post,
        detail={
            "board_id": post.board_id,
            "image_count": len(saved_files),
            "removed_image_count": len(files_to_delete),
        },
        request=request,
    )
    return post


def delete_post(*, post_id, actor, request=None):
    _require_member(actor)
    with transaction.atomic():
        post = _post_for_update(post_id)
        if not can_delete_post(actor, post):
            raise PermissionDenied
        post_images = list(post.images.all())
        detail = {
            "post_id": post.pk,
            "board_id": post.board_id,
            "author_id": post.author_id,
            "comment_count": post.comments.count(),
            "image_count": len(post_images),
        }
        record_audit(
            action="discussion.post.delete",
            user=actor,
            target=post,
            detail=detail,
            request=request,
        )
        post.delete()

    _delete_stored_files(
        [(image.image.storage, image.image.name) for image in post_images]
    )
    return detail["board_id"]


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


def _comment_for_update(comment_id):
    # 已经删掉的评论仍然锁得到、也仍然能再删一次：重复提交是一句无害的空操作，
    # 不必让第二个标签页上的按钮报 404。
    try:
        return Comment.all_objects.select_for_update().get(pk=comment_id)
    except Comment.DoesNotExist as exc:
        raise DiscussionNotFound from exc


def delete_comment(*, comment_id, actor, request=None):
    """把一条评论标记为已删除，返回它所属的板块与帖子。

    作者与管理员都能删（判定见 ``can_delete_comment``）。删除记在行上而不落盘，
    所以这里不碰任何文件；重复删除是空操作，不会重写原始删除人与删除时间。
    """
    _require_member(actor)
    with transaction.atomic():
        comment = _comment_for_update(comment_id)
        if not can_delete_comment(actor, comment):
            raise PermissionDenied
        if comment.deleted_at is not None:
            return comment.post.board_id, comment.post_id
        comment.soft_delete(actor=actor)
        record_audit(
            action="discussion.comment.delete",
            user=actor,
            target=comment,
            detail={
                "post_id": comment.post_id,
                "board_id": comment.post.board_id,
                "author_id": comment.author_id,
                "is_author": comment.author_id == actor.pk,
            },
            request=request,
        )
        return comment.post.board_id, comment.post_id


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
