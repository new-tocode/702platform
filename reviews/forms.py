"""Reviewer verdict form."""

from django import forms

from .models import ReviewAssignment


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
