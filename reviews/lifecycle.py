"""一轮送审的状态机，以及两道关（初审／评审）各自的措辞与口径。

取值、迁移表、拒绝文案、阶段表都只在这里写一份：

* 模型上的同名常量是本模块的**别名**，历史与模板里的语义不变；
* 服务层改 ``ProjectSubmission.status`` 一律经 :func:`transition`，给用户看的
  拒绝话一律经 :func:`transition_refusal`；
* 模板问模型属性（``status_tone``／``is_*``），不再比较 ``status == 'approved'``
  这类字面量；
* 每道关「谁有资格、轮次停在哪才轮得到它、审计动作叫什么」收在 :data:`STAGES`
  的一条 :class:`StageRules` 里——加一道关等于加一条记录。
"""

from typing import NamedTuple

from django.utils import timezone


# --- 轮次状态 ---------------------------------------------------------------

PRELIMINARY_PENDING = "preliminary_pending"
PENDING = "pending"
APPROVED = "approved"
NEEDS_REVISION = "needs_revision"

STATUS_CHOICES = (
    (PRELIMINARY_PENDING, "初审中"),
    (PENDING, "评审中"),
    (APPROVED, "已通过"),
    (NEEDS_REVISION, "需修改"),
)

#: 尚未出结论的两个状态。「本轮还在进行吗」一律问它，不要比单一取值。
OPEN_STATUSES = (PRELIMINARY_PENDING, PENDING)

#: 模板语气（``chip-{{ tone }}``／``.spec .v.{{ tone }}``）。与今天逐字一致：
#: 项目组列表用 ``chip-on`` 表示进行中；详情页的 ``.v`` 只有 ``.ok``／``.warn``
#: 两条样式，多出来的 ``on`` 类不落地任何外观。
STATUS_TONES = {
    PRELIMINARY_PENDING: "on",
    PENDING: "on",
    APPROVED: "ok",
    NEEDS_REVISION: "warn",
}


# --- 任务阶段 ---------------------------------------------------------------

STAGE_PRELIMINARY = "preliminary"
STAGE_REVIEW = "review"
STAGE_CHOICES = ((STAGE_PRELIMINARY, "初审"), (STAGE_REVIEW, "评审"))

TASK_PENDING = "pending"
TASK_COMPLETED = "completed"
TASK_RELEASED = "released"

#: 任务状态存在一个字段里，所以只能有一套 choices——存中性的说法；
#: 每一道关自己的叫法（待初审／待评审……）由 ReviewTask.status_label 按
#: ``(stage, status)`` 取。
TASK_STATUS_CHOICES = (
    (TASK_PENDING, "待处理"),
    (TASK_COMPLETED, "已完成"),
    (TASK_RELEASED, "已释放"),
)

TASK_STATUS_LABELS = {
    (STAGE_PRELIMINARY, TASK_PENDING): "待初审",
    (STAGE_PRELIMINARY, TASK_COMPLETED): "已初审",
    (STAGE_PRELIMINARY, TASK_RELEASED): "已释放",
    (STAGE_REVIEW, TASK_PENDING): "待评审",
    (STAGE_REVIEW, TASK_COMPLETED): "已完成",
    (STAGE_REVIEW, TASK_RELEASED): "已释放",
}

DECISION_APPROVE = "approve"
DECISION_REVISE = "revise"
DECISION_CHOICES = ((DECISION_APPROVE, "通过"), (DECISION_REVISE, "需修改"))


class StageRules(NamedTuple):
    """一道关自己的全部口径——改规则只改这一条记录。"""

    label: str  # 初审 / 评审
    holder_label: str  # 初审人 / 评审人
    qualification: str  # accounts.User 上的资格字段名
    open_status: str  # 轮次停在这个状态时，这道关才可提交、才可改派
    submit_action: str  # 审计动作名（沿用合并前的字符串，历史记录保持连续）
    reassign_action: str


STAGES = {
    STAGE_PRELIMINARY: StageRules(
        label="初审",
        holder_label="初审人",
        qualification="is_preliminary_reviewer",
        open_status=PRELIMINARY_PENDING,
        submit_action="reviews.preliminary.complete",
        reassign_action="reviews.preliminary.reassign",
    ),
    STAGE_REVIEW: StageRules(
        label="评审",
        holder_label="评审人",
        qualification="is_reviewer",
        open_status=PENDING,
        submit_action="reviews.assignment.complete",
        reassign_action="reviews.assignment.reassign",
    ),
}


# --- 迁移表 -----------------------------------------------------------------

class IllegalTransition(RuntimeError):
    """代码走到了不该走的分支——给用户看的话由 :func:`transition_refusal` 提供。"""


class Transition(NamedTuple):
    """一次迁移：落到哪个状态、可以从哪儿出发、不能出发时怎么解释。"""

    to: str
    allowed_from: tuple
    refused: str
    stamps_decided_at: bool = False


PRELIMINARY_APPROVED = "preliminary.approved"
PRELIMINARY_REVISED = "preliminary.revised"
REVIEWS_APPROVED = "reviews.approved"
REVIEWS_REVISED = "reviews.revised"
OVERRIDE_APPROVED = "override.approved"
OVERRIDE_REVISED = "override.revised"

TRANSITIONS = {
    PRELIMINARY_APPROVED: Transition(
        PENDING,
        (PRELIMINARY_PENDING,),
        "该轮送审已不在初审环节。",
    ),
    PRELIMINARY_REVISED: Transition(
        NEEDS_REVISION,
        (PRELIMINARY_PENDING,),
        "该轮送审已不在初审环节。",
        stamps_decided_at=True,
    ),
    REVIEWS_APPROVED: Transition(
        APPROVED,
        (PENDING,),
        "该轮送审已不在评审环节。",
        stamps_decided_at=True,
    ),
    REVIEWS_REVISED: Transition(
        NEEDS_REVISION,
        (PENDING,),
        "该轮送审已不在评审环节。",
        stamps_decided_at=True,
    ),
    OVERRIDE_APPROVED: Transition(
        APPROVED,
        OPEN_STATUSES,
        "本轮已经出过结论",
        stamps_decided_at=True,
    ),
    OVERRIDE_REVISED: Transition(
        NEEDS_REVISION,
        OPEN_STATUSES,
        "本轮已经出过结论",
        stamps_decided_at=True,
    ),
}


def transition_refusal(submission, event):
    """这次迁移不允许时返回给用户看的那句话；允许时返回 ``None``。"""
    rule = TRANSITIONS[event]
    if submission.status in rule.allowed_from:
        return None
    return rule.refused


def transition(submission, event, *, at=None):
    """**唯一**给 ``ProjectSubmission.status`` 赋值的地方。

    调用方先用 :func:`transition_refusal` 把话说清楚，再走到这里；真从非法状态
    撞进来属于代码错误，抛 :class:`IllegalTransition`。
    """
    rule = TRANSITIONS[event]
    if submission.status not in rule.allowed_from:
        raise IllegalTransition(f"{event} 不能从 {submission.status} 出发。")
    submission.status = rule.to
    fields = ["status"]
    if rule.stamps_decided_at:
        submission.decided_at = at or timezone.now()
        fields.append("decided_at")
    submission.save(update_fields=fields)
    return submission
