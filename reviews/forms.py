"""Forms for submitting a project proposal for review and for reviewing it."""

from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from projects.validators import validate_proposal_file

from . import lifecycle
from .models import REVIEW_TYPE_CHOICES, ReviewTask, ReviewerLeave
from .services import eligible_holders


User = get_user_model()


#: ``<input type="datetime-local">`` only accepts the literal "T" form. The
#: zh-hans localised default renders as "2026/09/20 14:30", which the browser
#: silently drops, leaving the field blank — so the format is pinned here.
DATETIME_LOCAL_FORMAT = "%Y-%m-%dT%H:%M"
DATETIME_LOCAL_INPUT_FORMATS = ["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"]


class SubmissionForm(forms.Form):
    """Choose the kind of review a round needs, plus an optional note."""

    review_type = forms.ChoiceField(
        label=_("评审类型"),
        choices=REVIEW_TYPE_CHOICES,
        help_text=_(
            "决定初审通过后需要几名评审人：竞赛类 3 人；"
            "大创中期、结题 2 人；大创立项 1 人。"
        ),
    )
    message = forms.CharField(
        label=_("提交说明"),
        required=False,
        widget=forms.Textarea(
            attrs={"rows": 3, "placeholder": _("例如：申请开题、申请参加 XX 竞赛")}
        ),
    )


class DecisionForm(forms.Form):
    """一次判定的形状：一个结论 + 一段意见——两道关共用的部分。

    初审直接用这个基类（它给的是理由，不是稿子），评审在它之上多一个批注版字段。
    标签按阶段给全（「初审决定」「评审决定」这类），不做字符串拼接——拼出来的
    话翻译不了；所以两个页面上的措辞与合并前逐字相同。
    """

    #: 子类覆盖：这一道关自己的两个标签与意见栏说明。
    decision_label = _("评审决定")
    comment_label = _("评审意见")
    comment_help = _("请说明通过或需要修改的理由。")

    decision = forms.ChoiceField(
        choices=ReviewTask.DECISION_CHOICES,
        widget=forms.RadioSelect,
    )
    comment = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 6}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["decision"].label = self.decision_label
        self.fields["comment"].label = self.comment_label
        self.fields["comment"].help_text = self.comment_help


class PreliminaryReviewForm(DecisionForm):
    """初审的判定：放行，还是打回。

    没有批注版字段——初审是关卡，产出的是理由；要附批注版的是评审人那一侧。
    """

    decision_label = _("初审决定")
    comment_label = _("初审意见")
    decision_help = _(
        "通过后按送审类型随机分配评审人，进入正式评审；"
        "需修改则本轮直接打回项目组，不分配评审人。"
    )
    comment_help = _("请说明通过或需要修改的理由；打回时项目组会据此修改项目书。")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["decision"].help_text = self.decision_help


class ReviewForm(DecisionForm):
    """评审的判定：通过还是需修改，可另附一份批注版项目书。"""

    comment_help = _("请说明通过或需要修改的理由。")

    annotated_file = forms.FileField(
        label=_("批注版项目书"),
        required=False,
        validators=[validate_proposal_file],
        help_text=_(
            "选填；支持 doc、docx、pdf。可在项目书上直接批注后上传，"
            "也可只填文字意见。请勿在文件属性中保留可识别个人身份的信息。"
        ),
    )


def _datetime_local_widget():
    return forms.DateTimeInput(
        format=DATETIME_LOCAL_FORMAT, attrs={"type": "datetime-local"}
    )


class ReviewerLeaveForm(forms.ModelForm):
    """Register a review-leave window: two time points plus an optional reason.

    The window covers both kinds of task the platform may hand out — 初审 and
    评审 — since it describes when the person is away, not what they are away
    from.
    """

    starts_at = forms.DateTimeField(
        label=_("请假开始"),
        input_formats=DATETIME_LOCAL_INPUT_FORMATS,
        widget=_datetime_local_widget(),
    )
    ends_at = forms.DateTimeField(
        label=_("请假结束"),
        input_formats=DATETIME_LOCAL_INPUT_FORMATS,
        widget=_datetime_local_widget(),
        help_text=_(
            "请假期间不会被分配新的初审或评审请求，到点自动恢复；"
            "已有的任务不受影响。"
        ),
    )

    class Meta:
        model = ReviewerLeave
        fields = ("starts_at", "ends_at", "reason")
        widgets = {
            "reason": forms.Textarea(
                attrs={"rows": 2, "placeholder": _("例如：考试周、外出比赛")}
            ),
        }

    def clean(self):
        cleaned = super().clean()
        starts_at = cleaned.get("starts_at")
        ends_at = cleaned.get("ends_at")
        if starts_at and ends_at and ends_at <= starts_at:
            self.add_error("ends_at", _("请假结束时间必须晚于开始时间。"))
        return cleaned


class AdminReassignTaskForm(forms.ModelForm):
    """管理员把一张还没交的任务卡换个人——两道关共用这一个表单。

    与 ``ReviewTaskAdmin.save_model`` 的契约：表单只负责给候选人，**没有**发言权
    决定能不能换（校验与审计都在 ``reassign_task``），``save()`` 也从不被使用。
    候选名单来自与抽人同一个 ``eligible_holders(stage=…)``，两者因此不可能漂移。
    """

    class Meta:
        model = ReviewTask
        fields = ("reviewer",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        task = self.instance
        rules = lifecycle.STAGES[task.stage]
        submission = task.submission
        self.fields["reviewer"].label = rules.holder_label
        self.fields["reviewer"].help_text = (
            f"只列出有{rules.label}资格、启用中、非本项目组成员、未请假、"
            "且本轮尚未持有任务的人。"
        )
        candidates = eligible_holders(
            stage=task.stage,
            group=submission.group,
            submitter=submission.submitted_by,
            submission=submission,
        )
        # Keep the current holder among the choices, otherwise the select renders
        # empty and the administrator cannot see who holds it now.
        self.fields["reviewer"].queryset = candidates | User.objects.filter(
            pk=task.reviewer_id
        )
