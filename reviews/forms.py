"""Forms for submitting a project group's materials for review, and for reviewing."""

from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from . import lifecycle
from .models import REVIEW_TYPE_CHOICES, ReviewTask
from .services import eligible_holders
from .validators import REPLY_HELP_TEXT, validate_reply_file


User = get_user_model()


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
        # 无上限的文本字段是一条廉价的写入放大路径：一次请求就能塞进几百 MB，
        # 把库撑大、把后台列表与页面渲染拖慢。5000 字对「申请开题」这类说明足够宽裕。
        max_length=5000,
        widget=forms.Textarea(
            attrs={"rows": 3, "placeholder": _("例如：申请开题、申请参加 XX 竞赛")}
        ),
    )


class DecisionForm(forms.Form):
    """一次判定的形状：一个结论 + 一段意见——两道关共用的部分。

    初审直接用这个基类（它给的是理由，不是稿子），评审在它之上多一个评审回复字段。
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
        # 评审意见要写清楚理由，但不能没有上限——理由同上。5000 字远超正常意见长度。
        max_length=5000,
        widget=forms.Textarea(attrs={"rows": 6}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["decision"].label = self.decision_label
        self.fields["comment"].label = self.comment_label
        self.fields["comment"].help_text = self.comment_help


class PreliminaryReviewForm(DecisionForm):
    """初审的判定：放行，还是打回。

    没有评审回复字段——初审是关卡，产出的是理由；要附回复的是评审人那一侧。
    """

    decision_label = _("初审决定")
    comment_label = _("初审意见")
    decision_help = _(
        "通过后按送审类型随机分配评审人，进入正式评审；"
        "需修改则本轮直接打回项目组，不分配评审人。"
    )
    comment_help = _("请说明通过或需要修改的理由；打回时项目组会据此修改项目资料。")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["decision"].help_text = self.decision_help


class ReviewForm(DecisionForm):
    """评审的判定：通过还是需修改，可另附一份评审回复压缩包。

    文字意见是必填的（``comment``），压缩包是选填的：回复里放的是批注、补充材料
    这类东西，而「通过还是需修改、为什么」必须写在意见里，否则结论与理由分家。
    """

    comment_help = _("请说明通过或需要修改的理由。")

    reply_file = forms.FileField(
        label=_("评审回复"),
        required=False,
        validators=[validate_reply_file],
        help_text=REPLY_HELP_TEXT,
    )


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
            f"只列出有{rules.label}资格、启用中、非本项目组成员、"
            f"没有关掉{rules.label}接单开关、且本轮尚未持有任务的人。"
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
