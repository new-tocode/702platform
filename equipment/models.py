"""Equipment inventory and member borrowing records."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Equipment(models.Model):
    name = models.CharField("设备名称", max_length=200)
    category = models.CharField("分类", max_length=100, blank=True)
    total_count = models.PositiveIntegerField("总量", default=1)
    available_count = models.PositiveIntegerField("可借数量", default=1)
    description = models.TextField("说明", blank=True)
    is_active = models.BooleanField("启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "设备"
        verbose_name_plural = "设备"
        ordering = ("category", "name", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(available_count__lte=models.F("total_count")),
                name="equipment_available_lte_total",
            ),
        ]
        indexes = [
            models.Index(fields=("is_active", "category", "name")),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.available_count > self.total_count:
            raise ValidationError({"available_count": "可借数量不能超过设备总量。"})
        if self.pk:
            active_borrow_count = self.borrows.filter(
                status=EquipmentBorrow.BORROWED,
            ).count()
            if self.available_count + active_borrow_count > self.total_count:
                raise ValidationError(
                    {
                        "total_count": (
                            "设备总量不能小于当前可借数量与已借出数量之和。"
                        ),
                    }
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class EquipmentBorrow(models.Model):
    BORROWED = "borrowed"
    RETURNED = "returned"
    STATUS_CHOICES = (
        (BORROWED, "已借用"),
        (RETURNED, "已归还"),
    )

    equipment = models.ForeignKey(
        Equipment,
        on_delete=models.PROTECT,
        related_name="borrows",
        verbose_name="设备",
    )
    borrower = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="equipment_borrows",
        verbose_name="借用人",
    )
    borrow_date = models.DateField("借用日期", default=timezone.localdate)
    planned_return_date = models.DateField("计划归还日期")
    actual_return_date = models.DateField("实际归还日期", null=True, blank=True)
    status = models.CharField(
        "状态",
        max_length=16,
        choices=STATUS_CHOICES,
        default=BORROWED,
    )
    remark = models.TextField("备注", blank=True)
    created_at = models.DateTimeField("登记时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "设备借用记录"
        verbose_name_plural = "设备借用记录"
        ordering = ("-created_at", "-id")
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(status="borrowed", actual_return_date__isnull=True)
                    | Q(status="returned", actual_return_date__isnull=False)
                ),
                name="borrow_status_matches_return_date",
            ),
        ]
        indexes = [
            models.Index(fields=("borrower", "status", "-created_at")),
            models.Index(fields=("equipment", "status", "-created_at")),
        ]

    def __str__(self):
        return f"{self.equipment} - {self.borrower.get_username()}"

    def clean(self):
        super().clean()
        if self.planned_return_date and self.borrow_date:
            if self.planned_return_date < self.borrow_date:
                raise ValidationError({"planned_return_date": "计划归还日期不能早于借用日期。"})
        if self.status == self.BORROWED and self.actual_return_date:
            raise ValidationError({"actual_return_date": "未归还记录不能填写实际归还日期。"})
        if self.status == self.RETURNED and not self.actual_return_date:
            raise ValidationError({"actual_return_date": "已归还记录必须填写实际归还日期。"})
        if (
            self.actual_return_date
            and self.borrow_date
            and self.actual_return_date < self.borrow_date
        ):
            raise ValidationError({"actual_return_date": "实际归还日期不能早于借用日期。"})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
