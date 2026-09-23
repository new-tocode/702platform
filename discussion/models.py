from django.conf import settings
from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _


class Board(models.Model):
    name_zh = models.CharField(_("中文名称"), max_length=80)
    name = models.CharField(_("英文名称"), max_length=80)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_discussion_boards",
        verbose_name=_("创建人"),
    )
    created_at = models.DateTimeField(_("创建时间"), auto_now_add=True)

    class Meta:
        verbose_name = _("社团空间板块")
        verbose_name_plural = _("社团空间板块")
        ordering = ("name_zh", "name", "pk")
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                name="discussion_board_name_ci_uniq",
            ),
        ]

    def __str__(self):
        return f"{self.name_zh} / {self.name}" if self.name_zh else self.name


class Post(models.Model):
    board = models.ForeignKey(
        Board,
        on_delete=models.PROTECT,
        related_name="posts",
        verbose_name=_("板块"),
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="discussion_posts",
        verbose_name=_("作者"),
    )
    title = models.CharField(_("标题"), max_length=200)
    content = models.TextField(_("正文"))
    is_pinned = models.BooleanField(_("置顶"), default=False)
    created_at = models.DateTimeField(_("发布时间"), auto_now_add=True)
    updated_at = models.DateTimeField(_("更新时间"), auto_now=True)

    class Meta:
        verbose_name = _("社团空间帖子")
        verbose_name_plural = _("社团空间帖子")
        ordering = ("-is_pinned", "-created_at", "-pk")
        indexes = [
            models.Index(
                fields=("board", "-is_pinned", "-created_at", "-id"),
                name="discussion_post_feed_idx",
            ),
        ]

    def __str__(self):
        return self.title


class Comment(models.Model):
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name="comments",
        verbose_name=_("帖子"),
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="discussion_comments",
        verbose_name=_("作者"),
    )
    content = models.TextField(_("评论内容"))
    created_at = models.DateTimeField(_("评论时间"), auto_now_add=True)

    class Meta:
        verbose_name = _("社团空间评论")
        verbose_name_plural = _("社团空间评论")
        ordering = ("created_at", "pk")
        indexes = [
            models.Index(
                fields=("post", "created_at"),
                name="discussion_comment_post_idx",
            ),
        ]

    def __str__(self):
        return f"{self.author} · {self.post}"
