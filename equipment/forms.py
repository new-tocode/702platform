"""Member and administrator forms for equipment records."""

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import Equipment, EquipmentBorrow


class EquipmentBorrowForm(forms.Form):
    planned_return_date = forms.DateField(
        label=_("计划归还日期"),
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={"type": "date"},
        ),
    )
    remark = forms.CharField(
        label=_("备注"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
    )

    def __init__(self, equipment, *args, **kwargs):
        self.equipment = equipment
        super().__init__(*args, **kwargs)

    def clean_planned_return_date(self):
        planned_return_date = self.cleaned_data["planned_return_date"]
        if planned_return_date < timezone.localdate():
            raise forms.ValidationError(_("计划归还日期不能早于今天。"))
        return planned_return_date


class EquipmentAdminForm(forms.ModelForm):
    class Meta:
        model = Equipment
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        total_count = cleaned_data.get("total_count")
        available_count = cleaned_data.get("available_count")
        if (
            total_count is not None
            and available_count is not None
            and available_count > total_count
        ):
            self.add_error("available_count", "可借数量不能超过设备总量。")
        if self.instance.pk and total_count is not None and available_count is not None:
            active_borrow_count = self.instance.borrows.filter(
                status=EquipmentBorrow.BORROWED,
            ).count()
            if available_count + active_borrow_count > total_count:
                self.add_error(
                    "total_count",
                    "设备总量不能小于当前可借数量与已借出数量之和。",
                )
        return cleaned_data
