"""请假窗口退场：接单状态改成 ``User`` 上的两个开关。

窗口那套东西（起止时间 + 事由 + 后台可改）换成「本人随时可开可关」的开关，
所以这张表连同它的登记/取消服务一起删掉。

**删表前先搬一次数据**：迁移跑起来时正在请假的人（窗口覆盖当下这一刻），把他的
两道开关都置为关闭——不这么做，部署那一刻他们会被静默地重新纳入抽签，而本人
以为自己还在请假。已经结束或还没开始的窗口不搬：前者本来就该恢复接单，后者
在旧机制里也还没生效，本人需要时自己去开。

反向迁移把表建回来（Django 自动生成的反向就是重建结构），但**开关状态不会跟着
回到窗口**——数据只往一个方向搬，这是这类替换的固有代价。
"""

from django.db import migrations
from django.utils import timezone


def carry_over_active_leave(apps, schema_editor):
    """把「此刻正在请假」的人映射成两道开关都关闭。"""
    ReviewerLeave = apps.get_model("reviews", "ReviewerLeave")
    User = apps.get_model("accounts", "User")

    now = timezone.now()
    reviewer_ids = (
        ReviewerLeave.objects.filter(starts_at__lte=now, ends_at__gt=now)
        .values_list("reviewer_id", flat=True)
        .distinct()
    )
    User.objects.filter(pk__in=list(reviewer_ids)).update(
        receives_preliminary_tasks=False,
        receives_review_tasks=False,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("reviews", "0010_archivedproposal_sha256_reviewtask_sha256"),
        # 开关字段得先在库里，搬运才写得进去。
        ("accounts", "0015_user_receives_preliminary_tasks_and_more"),
    ]

    operations = [
        migrations.RunPython(
            carry_over_active_leave,
            migrations.RunPython.noop,
        ),
        migrations.DeleteModel(
            name="ReviewerLeave",
        ),
    ]
