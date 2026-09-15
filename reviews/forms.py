"""Forms for submitting a project proposal for review and for reviewing it."""

from django import forms

from projects.validators import validate_proposal_file

from .models import REVIEW_TYPE_CHOICES, ReviewAssignment, ReviewerLeave


#: ``<input type="datetime-local">`` only accepts the literal "T" form. The
#: zh-hans localised default renders as "2026/09/20 14:30", which the browser
#: silently drops, leaving the field blank — so the format is pinned here.
DATETIME_LOCAL_FORMAT = "%Y-%m-%dT%H:%M"
DATETIME_LOCAL_INPUT_FORMATS = ["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"]


class SubmissionForm(forms.Form):
    """Choose the kind of review a round needs, plus an optional note."""

    review_type = forms.ChoiceField(
        label="评审类型",
        choices=REVIEW_TYPE_CHOICES,
        help_text="决定本轮需要几名评审人：竞赛类 3 人；大创中期、结题 2 人；大创立项 1 人。",
    )
    message = forms.CharField(
        label="提交说明",
        required=False,
        widget=forms.Textarea(
            attrs={"rows": 3, "placeholder": "例如：申请开题、申请参加 XX 竞赛"}
        ),
    )


class ReviewForm(forms.Form):
    decision = forms.ChoiceField(
        label="评审决定",
        choices=ReviewAssignment.DECISION_CHOICES,
        widget=forms.RadioSelect,
    )
    comment = forms.CharField(
        label="评审意见",
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text="请说明通过或需要修改的理由。",
    )
    annotated_file = forms.FileField(
        label="批注版项目书",
        required=False,
        validators=[validate_proposal_file],
        help_text=(
            "选填；支持 doc、docx、pdf。可在项目书上直接批注后上传，"
            "也可只填文字意见。请勿在文件属性中保留可识别个人身份的信息。"
        ),
    )


def _datetime_local_widget():
    return forms.DateTimeInput(
        format=DATETIME_LOCAL_FORMAT, attrs={"type": "datetime-local"}
    )


class ReviewerLeaveForm(forms.ModelForm):
    """Register a review-leave window: two time points plus an optional reason."""

    starts_at = forms.DateTimeField(
        label="请假开始",
        input_formats=DATETIME_LOCAL_INPUT_FORMATS,
        widget=_datetime_local_widget(),
    )
    ends_at = forms.DateTimeField(
        label="请假结束",
        input_formats=DATETIME_LOCAL_INPUT_FORMATS,
        widget=_datetime_local_widget(),
        help_text="请假期间不会被分配新的评审请求，到点自动恢复；已有的评审任务不受影响。",
    )

    class Meta:
        model = ReviewerLeave
        fields = ("starts_at", "ends_at", "reason")
        widgets = {
            "reason": forms.Textarea(
                attrs={"rows": 2, "placeholder": "例如：考试周、外出比赛"}
            ),
        }

    def clean(self):
        cleaned = super().clean()
        starts_at = cleaned.get("starts_at")
        ends_at = cleaned.get("ends_at")
        if starts_at and ends_at and ends_at <= starts_at:
            self.add_error("ends_at", "请假结束时间必须晚于开始时间。")
        return cleaned
