"""Forms for submitting a project proposal for review and for reviewing it."""

from django import forms
from django.contrib.auth import get_user_model

from projects.validators import validate_proposal_file

from .models import (
    REVIEW_TYPE_CHOICES,
    PreliminaryReview,
    ReviewAssignment,
    ReviewerLeave,
)
from .services import eligible_preliminary_reviewers, eligible_reviewers


User = get_user_model()


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
        help_text=(
            "决定初审通过后需要几名评审人：竞赛类 3 人；"
            "大创中期、结题 2 人；大创立项 1 人。"
        ),
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


class PreliminaryReviewForm(forms.Form):
    """The 初审 verdict: pass the proposal on, or send it back to the group.

    Same two verdicts as a review, but no annotated copy: the 初审 is a gate —
    what it produces is the reason it passed or bounced, and the group reads it
    off the group detail page.
    """

    decision = forms.ChoiceField(
        label="初审决定",
        choices=PreliminaryReview.DECISION_CHOICES,
        widget=forms.RadioSelect,
        help_text=(
            "通过后按送审类型随机分配评审人，进入正式评审；"
            "需修改则本轮直接打回项目组，不分配评审人。"
        ),
    )
    comment = forms.CharField(
        label="初审意见",
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text="请说明通过或需要修改的理由；打回时项目组会据此修改项目书。",
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
        label="请假开始",
        input_formats=DATETIME_LOCAL_INPUT_FORMATS,
        widget=_datetime_local_widget(),
    )
    ends_at = forms.DateTimeField(
        label="请假结束",
        input_formats=DATETIME_LOCAL_INPUT_FORMATS,
        widget=_datetime_local_widget(),
        help_text=(
            "请假期间不会被分配新的初审或评审请求，到点自动恢复；"
            "已有的任务不受影响。"
        ),
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


class AdminReassignReviewerForm(forms.ModelForm):
    """Administrator-side swap of one pending review task to another reviewer.

    Only ``reviewer`` is exposed; the other fields stay read-only on the change
    page. This form deliberately has no say in *whether* a swap is legal and its
    ``save()`` is never used — the write goes through ``reassign_reviewer`` (see
    ``ReviewAssignmentAdmin.save_model``), which owns the status rules and the
    audit trail. The candidate list comes from the same ``eligible_reviewers``
    that draws reviewers when a round is let through, so the two cannot drift
    apart.
    """

    class Meta:
        model = ReviewAssignment
        fields = ("reviewer",)
        labels = {"reviewer": "评审人"}
        help_texts = {
            "reviewer": (
                "只列出有评审资格、非本项目组成员、未请假、且本轮尚未分配的人"
                "（本轮的初审人也不在其中）。"
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        assignment = self.instance
        submission = assignment.submission
        candidates = eligible_reviewers(
            group=submission.group,
            submitter=submission.submitted_by,
            submission=submission,
        )
        # Keep the current reviewer among the choices, otherwise the select
        # renders empty and the administrator cannot see who holds it now.
        self.fields["reviewer"].queryset = candidates | User.objects.filter(
            pk=assignment.reviewer_id
        )


class AdminReassignPreliminaryReviewerForm(forms.ModelForm):
    """Administrator-side swap of one pending 初审 task to another 初审人.

    The 初审 counterpart of :class:`AdminReassignReviewerForm`, and it exists for
    the same reason: without it, a 初审人 who cannot be reached leaves the round
    stuck at 初审中 with no way in. Only the reviewer may be edited, and the write
    goes through ``reassign_preliminary_reviewer``.
    """

    class Meta:
        model = PreliminaryReview
        fields = ("reviewer",)
        labels = {"reviewer": "初审人"}
        help_texts = {
            # 与候选 queryset 逐项对齐：这里少写一项，管理员就会以为某个不在
            # 列表里的人该出现。评审侧的同一句话在 AdminReassignReviewerForm。
            "reviewer": (
                "只列出有初审资格、启用中、非本项目组成员、未请假、"
                "且本轮尚未持有任务的人。"
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        preliminary = self.instance
        submission = preliminary.submission
        candidates = eligible_preliminary_reviewers(
            group=submission.group,
            submitter=submission.submitted_by,
            submission=submission,
        )
        # Keep the current 初审人 among the choices so the select shows who holds
        # the task now; the service still refuses a swap that changes nothing.
        self.fields["reviewer"].queryset = candidates | User.objects.filter(
            pk=preliminary.reviewer_id
        )
