import logging
import mimetypes
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import FileResponse, Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from core.permissions import is_admin, require

from .forms import BoardForm, CommentForm, PostForm
from .models import Post, PostImage
from .permissions import can_edit_post, can_pin_post, can_view_space
from .selectors import board_list, member_directory, posts_for_board
from .services import (
    BoardNameTaken,
    BoardNotEmpty,
    DiscussionError,
    DiscussionNotFound,
    create_board,
    create_comment,
    create_post,
    delete_board,
    delete_post,
    set_post_pinned,
    update_post,
)


logger = logging.getLogger(__name__)
POSTS_PER_PAGE = 12


def _require_member(request):
    require(
        request,
        can_view_space(request.user),
        "discussion.permission.denied",
    )


def _space_context(request, *, selected_board=None):
    boards = board_list()
    if selected_board is None:
        selected_board = boards.first()

    posts_page = None
    if selected_board is not None:
        paginator = Paginator(posts_for_board(selected_board), POSTS_PER_PAGE)
        posts_page = paginator.get_page(request.GET.get("page"))

    member_query = request.GET.get("q", "").strip()
    return {
        "boards": boards,
        "active_board": selected_board,
        "posts_page": posts_page,
        "members": member_directory(name_query=member_query),
        "member_query": member_query,
        "board_form": BoardForm(),
        "can_manage_boards": request.user.is_superuser,
        "is_admin": is_admin(request.user),
    }


def _render_space(request, *, selected_board=None, status=200):
    return render(
        request,
        "discussion/space.html",
        _space_context(request, selected_board=selected_board),
        status=status,
    )


@login_required
@require_GET
def space(request):
    _require_member(request)
    return _render_space(request)


@login_required
@require_GET
def board(request, board_id):
    _require_member(request)
    selected_board = get_object_or_404(board_list(), pk=board_id)
    return _render_space(request, selected_board=selected_board)


@login_required
@require_http_methods(["GET", "POST"])
def post_new(request, board_id):
    _require_member(request)
    selected_board = get_object_or_404(board_list(), pk=board_id)
    form = PostForm(
        request.POST if request.method == "POST" else None,
        request.FILES if request.method == "POST" else None,
    )
    if request.method == "POST" and form.is_valid():
        try:
            post = create_post(
                board_id=selected_board.pk,
                title=form.cleaned_data["title"],
                content=form.cleaned_data["content"],
                actor=request.user,
                images=form.cleaned_data["images"],
                request=request,
            )
        except DiscussionNotFound as exc:
            raise Http404 from exc
        except DiscussionError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, _("帖子已发布。"))
            return redirect("discussion:board", board_id=post.board_id)

    return render(
        request,
        "discussion/post_form.html",
        {
            "form": form,
            "active_board": selected_board,
            "page_heading": _("发布帖子"),
            "submit_label": _("发布帖子"),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def post_edit(request, post_id):
    _require_member(request)
    post = get_object_or_404(
        Post.objects.select_related("board").prefetch_related("images"),
        pk=post_id,
    )
    if not can_edit_post(request.user, post):
        logger.warning(
            "discussion.post.edit.denied username=%s post_id=%s",
            request.user.get_username(),
            post.pk,
            extra={"request_id": getattr(request, "request_id", "-")},
        )
        raise PermissionDenied

    form = PostForm(
        request.POST if request.method == "POST" else None,
        request.FILES if request.method == "POST" else None,
        instance=post,
        remove_image_ids=request.POST.getlist("remove_image"),
    )
    if request.method == "POST" and form.is_valid():
        try:
            update_post(
                post_id=post.pk,
                title=form.cleaned_data["title"],
                content=form.cleaned_data["content"],
                actor=request.user,
                images=form.cleaned_data["images"],
                remove_image_ids=request.POST.getlist("remove_image"),
                request=request,
            )
        except DiscussionNotFound as exc:
            raise Http404 from exc
        except DiscussionError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, _("帖子已更新。"))
            return redirect("discussion:board", board_id=post.board_id)

    return render(
        request,
        "discussion/post_form.html",
        {
            "form": form,
            "active_board": post.board,
            "page_heading": _("编辑帖子"),
            "submit_label": _("保存修改"),
            "post": post,
            "post_images": post.images.all(),
        },
    )


@login_required
@require_POST
def post_delete(request, post_id):
    _require_member(request)
    try:
        board_id = delete_post(
            post_id=post_id,
            actor=request.user,
            request=request,
        )
    except DiscussionNotFound as exc:
        raise Http404 from exc
    except PermissionDenied:
        logger.warning(
            "discussion.post.delete.denied username=%s post_id=%s",
            request.user.get_username(),
            post_id,
            extra={"request_id": getattr(request, "request_id", "-")},
        )
        raise
    messages.success(request, _("帖子已删除。"))
    return redirect("discussion:board", board_id=board_id)


@login_required
@require_GET
def post_image(request, image_id):
    """帖子图片只发给能进社团空间的账号：MEDIA 是公开目录，不能直接把路径交出去。"""
    _require_member(request)
    image = get_object_or_404(PostImage, pk=image_id)
    try:
        file_handle = image.image.open("rb")
    except FileNotFoundError as exc:
        raise Http404 from exc
    content_type = (
        mimetypes.guess_type(image.image.name)[0] or "application/octet-stream"
    )
    return FileResponse(
        file_handle,
        as_attachment=False,
        filename=f"post-image{Path(image.image.name).suffix.lower()}",
        content_type=content_type,
    )


@login_required
@require_POST
def comment_create(request, post_id):
    _require_member(request)
    post = get_object_or_404(Post.objects.select_related("board"), pk=post_id)
    form = CommentForm(request.POST)
    if form.is_valid():
        try:
            create_comment(
                post_id=post.pk,
                content=form.cleaned_data["content"],
                actor=request.user,
                request=request,
            )
        except DiscussionNotFound as exc:
            raise Http404 from exc
        except DiscussionError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, _("评论已发布。"))
    else:
        for error in form.errors.get("content", []):
            messages.error(request, error)
    return redirect("discussion:board", board_id=post.board_id)


@login_required
@require_POST
def post_pin(request, post_id):
    _require_member(request)
    require(
        request,
        can_pin_post(request.user),
        "discussion.post.pin.denied",
        post_id=post_id,
    )
    pinned_value = request.POST.get("is_pinned")
    if pinned_value not in {"true", "false"}:
        return HttpResponseBadRequest(_("置顶状态无效。"))
    try:
        post = set_post_pinned(
            post_id=post_id,
            is_pinned=pinned_value == "true",
            actor=request.user,
            request=request,
        )
    except DiscussionNotFound as exc:
        raise Http404 from exc
    except PermissionDenied:
        logger.warning(
            "discussion.post.pin.denied username=%s post_id=%s",
            request.user.get_username(),
            post_id,
            extra={"request_id": getattr(request, "request_id", "-")},
        )
        raise
    messages.success(
        request,
        _("帖子已置顶。") if post.is_pinned else _("已取消置顶。"),
    )
    return redirect("discussion:board", board_id=post.board_id)


@login_required
@require_POST
def board_create(request):
    _require_member(request)
    require(
        request,
        request.user.is_superuser,
        "discussion.board.create.denied",
    )
    form = BoardForm(request.POST)
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect("discussion:space")

    try:
        board = create_board(
            name_zh=form.cleaned_data["name_zh"],
            name=form.cleaned_data["name"],
            actor=request.user,
            request=request,
        )
    except DiscussionError as exc:
        messages.error(request, str(exc))
        return redirect("discussion:space")
    messages.success(request, _("板块已创建。"))
    return redirect("discussion:board", board_id=board.pk)


@login_required
@require_POST
def board_delete(request, board_id):
    _require_member(request)
    require(
        request,
        request.user.is_superuser,
        "discussion.board.delete.denied",
        board_id=board_id,
    )
    try:
        delete_board(
            board_id=board_id,
            actor=request.user,
            request=request,
        )
    except DiscussionNotFound as exc:
        raise Http404 from exc
    except BoardNotEmpty as exc:
        messages.error(request, str(exc))
        return redirect("discussion:board", board_id=board_id)
    except PermissionDenied:
        logger.warning(
            "discussion.board.delete.denied username=%s board_id=%s",
            request.user.get_username(),
            board_id,
            extra={"request_id": getattr(request, "request_id", "-")},
        )
        raise
    messages.success(request, _("板块已删除。"))
    return redirect("discussion:space")
