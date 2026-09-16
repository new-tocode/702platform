"""把初审任务与评审任务合并成一张 ReviewTask。

两道关的任务形状相同（同一个持有人概念、同一个状态机、同一对结论、同样的改派与
释放规则），合并后这些规则只写一份。

**操作顺序是刻意的，两个方向都要对**：

1. 建新表（含三条约束：一人一轮一席、一轮恰好一条初审、超级评审那一票只属于评审）；
2. 正向回填：评审任务**保留原主键**——``ArchivedProposal`` 的外键与批注版下载链接
   都指向它，主键不变则归档引用与历史链接都不动；初审任务没有外部引用，主键由新表
   另给。回填后必须重置自增序列（显式主键不会推进它）；
3. 归档外键改名并改指新表：列里的值因为主键保留而天然正确，所以这是一次纯约束替换；
4. 反向才用的回填函数（``RunPython(noop, unseed)``）：反向执行时 Django 严格逆序，
   两张旧表在这之前已由 ``DeleteModel`` 的反向重建，**先灌数据、再改指外键**，FK
   才不会悬空；
5. 删两张旧表。

不用 ``RemoveField`` + ``AddField`` 换外键：反向会在非空表上执行
``ADD COLUMN … NOT NULL``，PostgreSQL 直接拒绝，反向迁移就废了。
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import projects.validators
import reviews.models


def seed_task_table(apps, schema_editor):
    """两张旧表 → 一张新表：评审行保留主键，初审行排在它后面。"""
    ReviewTask = apps.get_model("reviews", "ReviewTask")
    ReviewAssignment = apps.get_model("reviews", "ReviewAssignment")
    PreliminaryReview = apps.get_model("reviews", "PreliminaryReview")

    assignments = list(ReviewAssignment.objects.all())
    preliminaries = list(PreliminaryReview.objects.all())

    # 合并后 (submission, reviewer) 唯一。正常流程不会有人一人两席（初审人不会被
    # 抽为同一轮的评审人），手工数据可能越界——检测到就中止并报出行号，而不是静默
    # 丢一行：那会丢掉一条谁判过的记录。
    seats = {(row.submission_id, row.reviewer_id) for row in assignments}
    clash = [
        (row.submission_id, row.reviewer_id)
        for row in preliminaries
        if (row.submission_id, row.reviewer_id) in seats
    ]
    if clash:
        raise RuntimeError(
            "以下（轮次 id，账号 id）既持有初审任务又持有评审任务，合并后违反唯一"
            f"约束，请先人工处理：{clash}"
        )

    rows = [
        ReviewTask(
            id=row.pk,
            submission_id=row.submission_id,
            stage="review",
            reviewer_id=row.reviewer_id,
            status=row.status,
            decision=row.decision,
            comment=row.comment,
            is_override=row.is_override,
            annotated_file=row.annotated_file.name or "",
            assigned_at=row.assigned_at,
            completed_at=row.completed_at,
        )
        for row in assignments
    ]
    next_id = max((row.id for row in rows), default=0) + 1
    rows += [
        ReviewTask(
            id=next_id + index,
            submission_id=row.submission_id,
            stage="preliminary",
            reviewer_id=row.reviewer_id,
            status=row.status,
            decision=row.decision,
            comment=row.comment,
            assigned_at=row.assigned_at,
            completed_at=row.completed_at,
        )
        for index, row in enumerate(preliminaries)
    ]
    if not rows:
        return
    # assigned_at 是 auto_now_add：bulk_create 会把它改写成「现在」，所以先留底。
    keep_assigned_at = {row.pk: row.assigned_at for row in rows}
    ReviewTask.objects.bulk_create(rows, batch_size=500)
    for pk, assigned_at in keep_assigned_at.items():
        ReviewTask.objects.filter(pk=pk).update(assigned_at=assigned_at)
    # 显式主键不会推进序列，下一行就会撞 id。本项目固定 PostgreSQL。
    schema_editor.execute(
        "SELECT setval(pg_get_serial_sequence('reviews_reviewtask', 'id'),"
        " (SELECT MAX(id) FROM reviews_reviewtask))"
    )


def unseed_task_table(apps, schema_editor):
    """反向：把新表拆回两张，评审行同样保留主键，好让归档的外键再指回来。"""
    ReviewTask = apps.get_model("reviews", "ReviewTask")
    ReviewAssignment = apps.get_model("reviews", "ReviewAssignment")
    PreliminaryReview = apps.get_model("reviews", "PreliminaryReview")

    preliminaries = [
        PreliminaryReview(
            submission_id=row.submission_id,
            reviewer_id=row.reviewer_id,
            status=row.status,
            decision=row.decision,
            comment=row.comment,
            assigned_at=row.assigned_at,
            completed_at=row.completed_at,
        )
        for row in ReviewTask.objects.filter(stage="preliminary")
    ]
    assignments = [
        ReviewAssignment(
            id=row.pk,
            submission_id=row.submission_id,
            reviewer_id=row.reviewer_id,
            status=row.status,
            decision=row.decision,
            comment=row.comment,
            is_override=row.is_override,
            annotated_file=row.annotated_file.name or "",
            assigned_at=row.assigned_at,
            completed_at=row.completed_at,
        )
        for row in ReviewTask.objects.filter(stage="review")
    ]
    keep_preliminary_times = {row.pk: row.assigned_at for row in preliminaries if row.pk}
    keep_assignment_times = {row.pk: row.assigned_at for row in assignments}
    if preliminaries:
        PreliminaryReview.objects.bulk_create(preliminaries, batch_size=500)
    if assignments:
        ReviewAssignment.objects.bulk_create(assignments, batch_size=500)
    for pk, assigned_at in keep_preliminary_times.items():
        PreliminaryReview.objects.filter(pk=pk).update(assigned_at=assigned_at)
    for pk, assigned_at in keep_assignment_times.items():
        ReviewAssignment.objects.filter(pk=pk).update(assigned_at=assigned_at)
    for table in ("reviews_preliminaryreview", "reviews_reviewassignment"):
        schema_editor.execute(
            f"SELECT setval(pg_get_serial_sequence('{table}', 'id'),"
            f" (SELECT COALESCE(MAX(id), 1) FROM {table}))"
        )


class Migration(migrations.Migration):

    dependencies = [
        ("reviews", "0005_alter_projectsubmission_status_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ReviewTask",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "stage",
                    models.CharField(
                        choices=[("preliminary", "初审"), ("review", "评审")],
                        max_length=16,
                        verbose_name="阶段",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "待处理"),
                            ("completed", "已完成"),
                            ("released", "已释放"),
                        ],
                        default="pending",
                        max_length=16,
                        verbose_name="状态",
                    ),
                ),
                (
                    "decision",
                    models.CharField(
                        blank=True,
                        choices=[("approve", "通过"), ("revise", "需修改")],
                        max_length=16,
                        verbose_name="结论",
                    ),
                ),
                ("comment", models.TextField(blank=True, verbose_name="意见")),
                (
                    "is_override",
                    models.BooleanField(
                        default=False,
                        help_text="该行来自超级评审的一票决定：本轮结论由它单独敲定，等待中的任务随即被释放。",
                        verbose_name="超级评审决定",
                    ),
                ),
                (
                    "annotated_file",
                    models.FileField(
                        blank=True,
                        help_text="选填；支持 doc、docx、pdf。请勿在文件属性中保留可识别个人身份的信息。",
                        upload_to=reviews.models.upload_annotated_proposal,
                        validators=[projects.validators.validate_proposal_file],
                        verbose_name="批注版项目书",
                    ),
                ),
                (
                    "assigned_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="分配时间"),
                ),
                (
                    "completed_at",
                    models.DateTimeField(blank=True, null=True, verbose_name="完成时间"),
                ),
                (
                    "reviewer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="review_tasks",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="评审人",
                    ),
                ),
                (
                    "submission",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tasks",
                        to="reviews.projectsubmission",
                        verbose_name="送审",
                    ),
                ),
            ],
            options={
                "verbose_name": "评审任务",
                "verbose_name_plural": "评审任务",
                "ordering": ("status", "stage", "-assigned_at", "-id"),
                "indexes": [
                    models.Index(
                        fields=["reviewer", "status"], name="reviews_rev_reviewe_4f4ff5_idx"
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("submission", "reviewer"),
                        name="unique_submission_task_reviewer",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("stage", "preliminary")),
                        fields=("submission",),
                        name="unique_preliminary_task_per_submission",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("is_override", False), ("stage", "review"), _connector="OR"
                        ),
                        name="override_is_review_stage_only",
                    ),
                ],
            },
        ),
        migrations.RunPython(seed_task_table, migrations.RunPython.noop),
        # 改名与换约束要按这个次序：约束的字段名是「模型状态」的一部分，反向执行时
        # Django 严格逆序——先删新约束（按名字，不需要解析字段）、再改回外键指向、
        # 再把列名改回去，最后才加回旧约束（那时字段名已经正确）。换个次序反向就会
        # 撞上 "ArchivedProposal has no field named 'source_assignment'"。
        migrations.RemoveConstraint(
            model_name="archivedproposal",
            name="unique_archived_proposal_assignment",
        ),
        migrations.RenameField(
            model_name="archivedproposal",
            old_name="source_assignment",
            new_name="source_task",
        ),
        migrations.AlterField(
            model_name="archivedproposal",
            name="source_task",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="archived_proposals",
                to="reviews.reviewtask",
                verbose_name="来源任务",
            ),
        ),
        migrations.AddConstraint(
            model_name="archivedproposal",
            constraint=models.UniqueConstraint(
                fields=("source_task",), name="unique_archived_proposal_task"
            ),
        ),
        migrations.RunPython(migrations.RunPython.noop, unseed_task_table),
        migrations.DeleteModel(name="PreliminaryReview"),
        migrations.DeleteModel(name="ReviewAssignment"),
    ]
