"""竞赛报名的写操作。

事务、审计，以及「数据库约束冲突 → 领域异常」的翻译都在这里。视图只负责把
表单数据递进来、再把结果说给用户听——它过去把这些都揽在自己身上，于是
competitions 成了唯一一个把事务写进视图的应用。
"""

from django.db import IntegrityError, transaction
from django.utils.translation import gettext_lazy as _

from core.audit import record_audit

from .models import CompetitionRegistration


class RegistrationClosed(Exception):
    """报名已截止或已关闭，不能再改动这条登记。"""


class DuplicateRegistration(Exception):
    """该项目组已经登记过这场竞赛。

    ``(competition, group)`` 的唯一约束是这条规则的兜底；重复提交由数据库拦下，
    服务把它翻译成本异常，免得每个调用方各写一遍 IntegrityError 处理。
    """


def save_registration(
    *,
    competition,
    group,
    members,
    team_leader,
    actor,
    remark="",
    instance=None,
    request=None,
):
    """新建（``instance`` 为空）或修改一条竞赛报名，并留一条审计。

    报名是否开放、竞赛组长是否属于参赛成员这类判断在表单层；这里只管把这些
    数据落库、并保证同组同赛不出现第二条。
    """
    try:
        with transaction.atomic():
            if instance is None:
                registration = CompetitionRegistration.objects.create(
                    competition=competition,
                    group=group,
                    registered_by=actor,
                    team_leader=team_leader,
                    remark=remark,
                )
            else:
                registration = instance
                registration.group = group
                registration.team_leader = team_leader
                registration.remark = remark
                registration.save(
                    update_fields=["group", "team_leader", "remark", "updated_at"]
                )
            registration.members.set(members)
    except IntegrityError as exc:
        raise DuplicateRegistration from exc

    # 审计写在事务外，与合并前一致；新建时多记一个参赛人数（历史口径如此）。
    detail = {
        "competition_id": competition.pk,
        "group_id": registration.group_id,
    }
    if instance is None:
        detail["member_count"] = registration.members.count()
    record_audit(
        action=(
            "competitions.registration"
            if instance is None
            else "competitions.registration.update"
        ),
        user=actor,
        target=registration,
        detail=detail,
        request=request,
    )
    return registration


def withdraw_registration(*, registration, actor, request=None):
    """放弃报名。

    与报名、修改一样受截止时间约束：这三件事都是「改这条登记」，没有理由让其中
    一件事在截止后仍然可用。少了这道校验，截止、甚至名单已经报给主办方之后，联系
    人还能把记录删掉——真实后果是平台记录与已上报名单对不上，要等对账时才发现。

    审计的 detail 里是竞赛与项目组的 id，必须在删除前先取出来——记录没了就
    取不到了。审计本身仍写在删除之后，与合并前一致。
    """
    if not registration.competition.is_registration_open:
        raise RegistrationClosed(_("该竞赛已关闭报名或已超过报名截止时间，无法放弃。"))
    detail = {
        "competition_id": registration.competition_id,
        "group_id": registration.group_id,
    }
    registration.delete()
    record_audit(
        action="competitions.registration.withdraw",
        user=actor,
        detail=detail,
        request=request,
    )
