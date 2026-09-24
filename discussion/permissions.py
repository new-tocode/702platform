from core.permissions import is_admin


def is_member(user):
    """Return whether an account may enter the member-only workspace."""
    return bool(
        user
        and user.is_authenticated
        and getattr(user, "is_active", False)
        and not getattr(user, "must_change_password", False)
    )


def can_view_space(user):
    return is_member(user)


def can_create_board(user):
    return is_member(user) and bool(user.is_superuser)


def can_delete_board(user):
    return can_create_board(user)


def can_create_post(user):
    return is_member(user)


def can_comment(user):
    return is_member(user)


def can_edit_post(user, post):
    return is_member(user) and post.author_id == user.pk


def can_delete_post(user, post):
    return is_member(user) and (
        post.author_id == user.pk or is_admin(user)
    )


def can_delete_comment(user, comment):
    """评论作者可删自己的评论，管理员可删任意评论——与帖子的口径对称。"""
    return is_member(user) and (
        comment.author_id == user.pk or is_admin(user)
    )


def can_pin_post(user):
    return is_member(user) and is_admin(user)
