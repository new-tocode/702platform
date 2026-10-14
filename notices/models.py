"""Public and internal notices published by administrators."""

from django.conf import settings
from django.contrib.auth.models import Group
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from media.models import MediaFile


class Notice(models.Model):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONTACTS = "contacts"
    SCOPE_CHOICES = (
        (PUBLIC, "公开"),
        (INTERNAL, "内部"),
        (CONTACTS, "仅联系人可见"),
    )

    title = models.CharField("标题", max_length=200)
    content = models.TextField("正文", max_length=20000)
    scope = models.CharField(
        "可见范围",
        max_length=16,
        choices=SCOPE_CHOICES,
        default=PUBLIC,
    )
    is_pinned = models.BooleanField("置顶", default=False)
    visible_groups = models.ManyToManyField(
        Group,
        blank=True,
        related_name="visible_notices",
        verbose_name="可查看用户组",
        help_text="仅“内部”通知需要选择用户组；属于任一所选用户组的成员可以查看。“公开”和“仅联系人可见”通知无需选择。",
    )
    attachments = models.ManyToManyField(
        MediaFile,
        blank=True,
        related_name="notices",
        verbose_name="配图/视频",
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="published_notices",
        verbose_name="发布人",
    )
    published_at = models.DateTimeField("发布时间", default=timezone.now)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "通知公告"
        verbose_name_plural = "通知公告"
        ordering = ("-is_pinned", "-published_at", "-id")
        indexes = [
            models.Index(fields=("scope", "-published_at")),
            models.Index(fields=("scope", "-is_pinned", "-published_at")),
        ]

    def __str__(self):
        return self.title


class NoticeRead(models.Model):
    """一条「谁读过哪条通知」的回执，撑着「我的消息」的未读状态。

    未读 = 可见通知（``visibility.member_visible_notices``）减去本表——不物化
    消息副本，所以发布人删除通知后，成员的列表与计数里自然不再出现它；本表随
    通知级联清掉，不留孤儿（迁移里 ``on_delete=CASCADE``）。

    已读是高频、个人、幂等的操作，不写审计（与登录、评审提交不同），只在视图
    里记日志。
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notice_reads",
        verbose_name="用户",
    )
    notice = models.ForeignKey(
        Notice,
        on_delete=models.CASCADE,
        related_name="reads",
        verbose_name="通知",
    )
    read_at = models.DateTimeField("已读时间", default=timezone.now)

    class Meta:
        verbose_name = "通知已读回执"
        verbose_name_plural = "通知已读回执"
        constraints = [
            models.UniqueConstraint(
                fields=("user", "notice"),
                name="unique_notice_read_per_user",
            ),
        ]

    def __str__(self):
        return f"{self.user} → {self.notice}"


#: 一条私信的正文上限（字数）。与简介（1000）、评论（4000）一样是个「约」的数量级，
#: 模型字段与表单共用这一份常量，模板里的 maxlength 由表单的 widget 带出去。
DIRECT_MESSAGE_MAX_CHARS = 1500


class DirectMessage(models.Model):
    """一条私信：谁写给谁的、正文是什么。

    与其余事件型消息的分别在于**正文没有第二个家**：提及、评论、评审、申请那几类都
    指向一个另有主人的对象（帖子、评论、申请、轮次），消息行里只存引用；私信的正文
    就落在这里，由 ``Message.direct_message`` 引用它。所以「删除私信」就是删这一行
    ——通知行跟着级联走，与「来源删除即级联删行」是同一条口径。

    发信人／收信人也住在这里（与 ``GroupJoinRequest`` 存 applicant 同一分工）：通知
    行上的 ``actor`` / ``recipient`` 是给所有 kind 统一装配用的冗余列，私信的「来自」
    与「回给谁」一律以本表为准。

    **写入口只有成员侧**：后台那只 ``DirectMessageAdmin`` 是只读的（无增、无改、无删），
    也不写审计（见 ``../notices/README.md`` §5）——正文与收发关系是成员之间的东西，
    后台能查是为了「出了事看得到」，不是给运维留痕的。
    """

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="sent_direct_messages",
        verbose_name="发信人",
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="received_direct_messages",
        verbose_name="收信人",
    )
    body = models.TextField(
        "正文",
        max_length=DIRECT_MESSAGE_MAX_CHARS,
        # 这一句会出现在成员面上的表单里（verbose_name 只在后台出现），所以它是惰性译文。
        help_text=_("最多 1500 字。"),
    )
    created_at = models.DateTimeField("发送时间", default=timezone.now)

    class Meta:
        verbose_name = "私信"
        verbose_name_plural = "私信"
        ordering = ("-created_at", "-pk")

    def __str__(self):
        return f"{self.sender} → {self.recipient}"


class Message(models.Model):
    """事件型消息：一行一个收件人（@ 提及、评论、评审、申请类都走这里）。

    与广播型的 ``Notice`` 分工明确：通知按可见集合实时查、用 ``NoticeRead`` 记
    已读；事件型没有「可见集合」可言——发生时就落一行，来源删除就级联删行
    （与「删除的通知看不到」同一条口径）。

    行里只存**结构化引用与已读状态**，标题／链接／「状态」列由 ``notices.selectors``
    渲染时现取现算：帖子改了标题、轮次出了新结论、申请被处理了，消息里跟着变，不存副本。引用用
    字符串外键，notices 不在加载期依赖 discussion／reviews／projects。

    「哪一类消息挂哪个引用」不在库里加约束（都为空的行是写入函数的责任，见
    ``notices/services.py``）——六种引用的组合约束会让表结构比问题本身复杂。

    私信那一类（``DIRECT``）指过来的是 ``DirectMessage``：正文在那边，本行照旧只有
    引用与已读状态。
    """

    MENTION = "mention"
    COMMENT = "comment"
    DIRECT = "direct"
    REVIEW_PRELIMINARY = "review_preliminary"
    REVIEW = "review"
    REVIEW_RESULT = "review_result"
    JOIN_REQUEST = "join_request"
    JOIN_RESULT = "join_result"
    CREATE_REQUEST = "create_request"
    CREATE_RESULT = "create_result"
    KIND_CHOICES = (
        (MENTION, "提及"),
        (COMMENT, "评论"),
        (DIRECT, "私信"),
        (REVIEW_PRELIMINARY, "初审任务"),
        (REVIEW, "评审任务"),
        (REVIEW_RESULT, "评审结果"),
        (JOIN_REQUEST, "入组申请"),
        (JOIN_RESULT, "入组结果"),
        (CREATE_REQUEST, "建组申请"),
        (CREATE_RESULT, "建组结果"),
    )

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="messages",
        verbose_name="收件人",
    )
    kind = models.CharField("类型", max_length=20, choices=KIND_CHOICES)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_messages",
        verbose_name="发起人",
    )
    is_read = models.BooleanField("已读", default=False)
    read_at = models.DateTimeField("已读时间", null=True, blank=True)
    created_at = models.DateTimeField("产生时间", auto_now_add=True)

    post = models.ForeignKey(
        "discussion.Post",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="messages",
        verbose_name="帖子",
    )
    comment = models.ForeignKey(
        "discussion.Comment",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="messages",
        verbose_name="评论",
    )
    submission = models.ForeignKey(
        "reviews.ProjectSubmission",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="messages",
        verbose_name="送审轮次",
    )
    join_request = models.ForeignKey(
        "projects.GroupJoinRequest",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="messages",
        verbose_name="入组申请",
    )
    create_request = models.ForeignKey(
        "projects.GroupCreateRequest",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="messages",
        verbose_name="建组申请",
    )
    direct_message = models.ForeignKey(
        DirectMessage,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="messages",
        verbose_name="私信",
    )

    class Meta:
        verbose_name = "站内消息"
        verbose_name_plural = "站内消息"
        ordering = ("-created_at", "-pk")
        indexes = [
            models.Index(fields=("recipient", "is_read")),
            models.Index(fields=("recipient", "-created_at", "-id")),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} → {self.recipient}"
