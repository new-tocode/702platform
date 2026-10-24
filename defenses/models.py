"""Offline mock-defense requests and their issue-style discussion threads.

A request belongs to one project group and is raised by whoever may manage that
group (its contact, or an administrator). Reviewers read the requests on the
review area's schedule page, comment on them, and the applicant keeps editing
the request text until the applicant or an administrator settles it. Settling
closes the thread: the text and the whole comment history stay readable, but
nothing can be edited or added afterwards.

The request text is capped at :data:`DEFENSE_CONTENT_MAX_CHARS`; the help text
asks the applicant to state both the time and the place, because the schedule is
only useful when those two are written down.
"""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from projects.models import ProjectGroup


#: The request text is short on purpose: this is a scheduling note, not a
#: proposal. Both the model field and the form use this one number.
DEFENSE_CONTENT_MAX_CHARS = 500

#: A comment may be longer than the request it discusses.
DEFENSE_COMMENT_MAX_CHARS = 1000


class DefenseRequest(models.Model):
    """One project group's request for an offline mock defense.

    Status is the only state: ``OPEN`` while the schedule is still being worked
    out, ``CLOSED`` once the applicant or an administrator settles it. There is
    no unique constraint tying a group to one request — a group may need several
    mock defenses over time, and an unproductive thread can simply be closed and
    a new one opened.

    The applicant is frozen at creation time (``PROTECT``): transferring the
    group's contact later does not hand the request to the new contact. That is
    deliberate — the person who wrote the request is the person who keeps
    editing and closing it, mirroring how an issue keeps its author.
    """

    OPEN = "open"
    CLOSED = "closed"
    STATUS_CHOICES = (
        (OPEN, _("安排中")),
        (CLOSED, _("已确定")),
    )

    group = models.ForeignKey(
        ProjectGroup,
        on_delete=models.PROTECT,
        related_name="defense_requests",
        verbose_name="项目组",
    )
    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="defense_requests",
        verbose_name="申请人",
    )
    content = models.TextField(
        "答辩安排",
        max_length=DEFENSE_CONTENT_MAX_CHARS,
        help_text=_("请写明答辩的时间和地点，最多 500 字。"),
    )
    status = models.CharField(
        "状态",
        max_length=16,
        choices=STATUS_CHOICES,
        default=OPEN,
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="closed_defense_requests",
        verbose_name="关闭人",
    )
    closed_at = models.DateTimeField("关闭时间", null=True, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "线下模拟答辩申请"
        verbose_name_plural = "线下模拟答辩申请"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("status", "-created_at")),
        ]

    def __str__(self):
        return f"{self.group} · {self.applicant}（{self.get_status_display()}）"

    @property
    def is_open(self):
        return self.status == self.OPEN

    @property
    def is_closed(self):
        return self.status == self.CLOSED


class DefenseComment(models.Model):
    """One entry in a request's thread: a person's comment or an edit event.

    An edit event is written automatically whenever the applicant changes the
    request text. It stores no sentence of its own: the wording belongs to the
    template (``申请者修改了答辩申请``), so it follows the interface language
    instead of freezing one language into the database at write time. That is
    why ``kind`` exists instead of putting the sentence into ``body``.

    The author of an edit event is the applicant — the same person who edited
    the request — so the history needs no second actor column.
    """

    COMMENT = "comment"
    EDIT = "edit"
    KIND_CHOICES = (
        (COMMENT, _("评论")),
        (EDIT, _("修改")),
    )

    request = models.ForeignKey(
        DefenseRequest,
        on_delete=models.CASCADE,
        related_name="comments",
        verbose_name="答辩申请",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="defense_comments",
        verbose_name="作者",
    )
    kind = models.CharField(
        "类型",
        max_length=16,
        choices=KIND_CHOICES,
        default=COMMENT,
    )
    body = models.TextField(
        "正文",
        max_length=DEFENSE_COMMENT_MAX_CHARS,
        blank=True,
        help_text=_("最多 1000 字。"),
    )
    created_at = models.DateTimeField("发表时间", auto_now_add=True)

    class Meta:
        verbose_name = "答辩申请评论"
        verbose_name_plural = "答辩申请评论"
        ordering = ("created_at", "id")
        indexes = [
            models.Index(fields=("request", "created_at")),
        ]

    def __str__(self):
        return f"{self.request_id} · {self.author}（{self.get_kind_display()}）"

    @property
    def is_edit(self):
        return self.kind == self.EDIT

    @property
    def is_comment(self):
        return self.kind == self.COMMENT
