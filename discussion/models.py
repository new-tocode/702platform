from django.conf import settings
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .validators import post_image_upload_to, validate_post_image


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


class PostImage(models.Model):
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name="images",
        verbose_name=_("帖子"),
    )
    image = models.ImageField(
        _("帖子图片"),
        upload_to=post_image_upload_to,
        validators=[validate_post_image],
    )
    file_size = models.PositiveBigIntegerField(_("文件大小"), default=0, editable=False)
    created_at = models.DateTimeField(_("上传时间"), auto_now_add=True)

    class Meta:
        verbose_name = _("帖子图片")
        verbose_name_plural = _("帖子图片")
        ordering = ("created_at", "pk")

    def __str__(self):
        return f"{self.post} image #{self.pk}"

    def save(self, *args, **kwargs):
        if self.image:
            self.file_size = self.image.size
        self.full_clean()
        return super().save(*args, **kwargs)


class CommentQuerySet(models.QuerySet):
    def alive(self):
        return self.filter(deleted_at__isnull=True)


class CommentManager(models.Manager.from_queryset(CommentQuerySet)):
    """默认只给未删除的评论。

    「已删除的评论不出现在任何地方」应当是评论表自己的性质，而不是每个调用点
    各自记得加的那个条件——漏一处就会让删掉的评论从别处冒出来（反向关系
    ``post.comments`` 走的正是这个默认经理）。要看全部，包括谁在什么时候删了
    哪条，走 ``Comment.all_objects``。

    级联删除不受影响：Django 收集待删对象用的是 ``_base_manager``，那是一个
    不过滤的普通经理，删帖时软删除过的评论照样跟着走，不会留下孤儿行。
    """

    def get_queryset(self):
        return super().get_queryset().alive()


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
    # 删除是软删除：行与内容都留着，只在界面上让位给一行说明。硬删会让一条
    # 有人回过的评论凭空消失、连删过这件事都没有痕迹；删除动作另有审计。
    deleted_at = models.DateTimeField(_("删除时间"), null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deleted_comments",
        verbose_name=_("删除人"),
    )

    all_objects = CommentQuerySet.as_manager()
    objects = CommentManager()

    class Meta:
        verbose_name = _("社团空间评论")
        verbose_name_plural = _("社团空间评论")
        ordering = ("created_at", "pk")
        # 类体里 ``all_objects`` 写在前面，不指名的话默认经理就是它——
        # 反向关系 ``post.comments`` 会连已删除的评论一起给出来。
        default_manager_name = "objects"
        indexes = [
            models.Index(
                fields=("post", "created_at"),
                name="discussion_comment_post_idx",
            ),
        ]

    def __str__(self):
        return f"{self.author} · {self.post}"

    def soft_delete(self, *, actor):
        """标记删除。幂等：已经删过的不改原删除人与原删除时间。"""
        if self.deleted_at is not None:
            return self
        self.deleted_at = timezone.now()
        self.deleted_by = actor
        self.save(update_fields=["deleted_at", "deleted_by"])
        return self
