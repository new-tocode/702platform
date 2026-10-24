"""线下模拟答辩的写操作：创建、修改、评论与关闭。

四个动作都在事务里做；修改与关闭先 ``select_for_update()`` 锁住申请行再复查状态，
所以「关闭的同时还能不能改／评论」没有中间态：要么动作先完成，要么看到已关闭
被拒。创建不锁行——它不改变任何既有状态。

申请正文的**每一次实际变化**都自动写一条 ``kind=EDIT`` 的评论。文案不存在数据库
里，由模板渲染（见 :class:`defenses.models.DefenseComment`），这样它跟着界面语言走。
内容没变就不写：没有发生修改，就不该在讨论里多一条记录。
"""

import logging
from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.audit import record_audit
from notices import services as notices_services
from projects.models import ProjectGroup

from .models import (
    DEFENSE_COMMENT_MAX_CHARS,
    DEFENSE_CONTENT_MAX_CHARS,
    DefenseComment,
    DefenseRequest,
)
from .permissions import (
    can_close_request,
    can_comment,
    can_create_request,
    can_edit_request,
)


logger = logging.getLogger(__name__)

#: 双击「提交申请」或网络重试时，同一个人、同一个组、同一段正文在这么短的窗口内
#: 只会留下一条申请。它挡住的是误触，不是「有意再发一条」——后者总会改几个字，
#: 或等窗口过去。
CREATE_IDEMPOTENCY_WINDOW = timedelta(seconds=10)


class DefenseError(Exception):
    """线下答辩申请不能被创建、修改、评论或关闭。"""


def _clean_content(content):
    text = (content or "").strip()
    if not text:
        raise DefenseError(_("请填写答辩的时间与地点。"))
    if len(text) > DEFENSE_CONTENT_MAX_CHARS:
        raise DefenseError(
            _("答辩申请不能超过 %(limit)s 字。")
            % {"limit": DEFENSE_CONTENT_MAX_CHARS}
        )
    return text


def _clean_comment(body):
    text = (body or "").strip()
    if not text:
        raise DefenseError(_("评论内容不能为空。"))
    if len(text) > DEFENSE_COMMENT_MAX_CHARS:
        raise DefenseError(
            _("评论不能超过 %(limit)s 字。")
            % {"limit": DEFENSE_COMMENT_MAX_CHARS}
        )
    return text


def create_request(*, group, applicant, content, request=None):
    """创建一条「安排中」的申请，并给所有评审资格持有者发消息。

    返回 ``(申请, 是否新建)``。第二次提交同一段正文时复用刚建的那一条，不再
    发一轮消息——双击不该让每位评审人多收一条未读。

    创建前锁住项目组行再复查「谁能发起」：视图取到组之后，另一位管理员可能刚好
    完成联系人转让，用视图里那份旧对象复查会放行已经卸任的联系人。锁内复查把
    「创建」与「转让」排成先后两个状态，而不是交错。
    """
    text = _clean_content(content)

    with transaction.atomic():
        locked_group = ProjectGroup.objects.select_for_update().get(pk=group.pk)
        if not can_create_request(applicant, locked_group):
            raise PermissionDenied
        recent = (
            DefenseRequest.objects.filter(
                group=locked_group,
                applicant=applicant,
                status=DefenseRequest.OPEN,
                content=text,
                created_at__gte=timezone.now() - CREATE_IDEMPOTENCY_WINDOW,
            )
            .order_by("-created_at", "-id")
            .first()
        )
        if recent is not None:
            return recent, False
        defense_request = DefenseRequest.objects.create(
            group=locked_group,
            applicant=applicant,
            content=text,
        )
        notices_services.notify_defense_request(defense_request=defense_request)

    record_audit(
        action="defenses.request.create",
        user=applicant,
        target=defense_request,
        detail={"group_id": locked_group.pk},
        request=request,
    )
    logger.info(
        "defenses.request.create request_id=%s group_id=%s applicant=%s",
        defense_request.pk,
        locked_group.pk,
        applicant.get_username(),
    )
    return defense_request, True


def update_request(*, defense_request, content, actor, request=None):
    """申请人改正文；内容真的变了才自动留一条「申请者修改了答辩申请」。"""
    with transaction.atomic():
        locked = DefenseRequest.objects.select_for_update().get(
            pk=defense_request.pk
        )
        if not can_edit_request(actor, locked):
            raise PermissionDenied
        text = _clean_content(content)
        if text == locked.content:
            return locked, False
        locked.content = text
        locked.save(update_fields=["content", "updated_at"])
        DefenseComment.objects.create(
            request=locked,
            author=actor,
            kind=DefenseComment.EDIT,
        )
    record_audit(
        action="defenses.request.update",
        user=actor,
        target=locked,
        detail={"group_id": locked.group_id},
        request=request,
    )
    logger.info(
        "defenses.request.update request_id=%s group_id=%s actor=%s",
        locked.pk,
        locked.group_id,
        actor.get_username(),
    )
    return locked, True


def add_comment(*, defense_request, body, actor, request=None):
    """在「安排中」的申请下留一条评论。"""
    with transaction.atomic():
        locked = DefenseRequest.objects.select_for_update().get(
            pk=defense_request.pk
        )
        if not can_comment(actor, locked):
            raise PermissionDenied
        comment = DefenseComment.objects.create(
            request=locked,
            author=actor,
            kind=DefenseComment.COMMENT,
            body=_clean_comment(body),
        )
    record_audit(
        action="defenses.comment.create",
        user=actor,
        target=comment,
        detail={"request_id": locked.pk, "group_id": locked.group_id},
        request=request,
    )
    logger.info(
        "defenses.comment.create comment_id=%s request_id=%s actor=%s",
        comment.pk,
        locked.pk,
        actor.get_username(),
    )
    return comment


def close_request(*, defense_request, actor, request=None):
    """申请人或管理员关闭申请：状态转「已确定」，此后只读。"""
    with transaction.atomic():
        locked = DefenseRequest.objects.select_for_update().get(
            pk=defense_request.pk
        )
        if not can_close_request(actor, locked):
            raise PermissionDenied
        locked.status = DefenseRequest.CLOSED
        locked.closed_by = actor
        locked.closed_at = timezone.now()
        locked.save(update_fields=["status", "closed_by", "closed_at", "updated_at"])
    record_audit(
        action="defenses.request.close",
        user=actor,
        target=locked,
        detail={"group_id": locked.group_id},
        request=request,
    )
    logger.info(
        "defenses.request.close request_id=%s group_id=%s actor=%s",
        locked.pk,
        locked.group_id,
        actor.get_username(),
    )
    return locked
