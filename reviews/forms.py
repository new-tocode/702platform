"""Forms for submitting a project proposal for review and for reviewing it."""

from django import forms

from projects.validators import validate_proposal_file

from .models import REVIEW_TYPE_CHOICES, ReviewAssignment


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
