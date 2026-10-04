"""Award 加「获奖层级」，并按证书上的写法回填历史记录。

层级原先是 ``level`` 里的自由文本：「省一等奖」「东北赛区一等奖」「黑龙江赛区一等奖」
说的是同一层（省级），字面上却几乎没有共同的三元组——pg_trgm 在短串上实测只有 0.18，
远在判重阈值 0.55 之下，同一条奖于是被重复录入。层级因此提出来单独存：判重比它，不比
措辞；``level`` 退成「证书上的写法」（verbose_name 一并改掉），只作展示与搜索。

回填规则见 ``content.tier_rules.derive_tier``：纯文本函数、不碰模型，迁移里可以直接引。
规则日后若再调整，已跑过这条迁移的库不受影响（判重比的是记录上存下来的 ``tier``，
不现算），只有新建库的回填结果会跟着变。

认不出层级的记录留空、打印出来交给人工在后台补：判重对空值的规矩是「没填就不比这一项」，
它不会拦住谁，但也拦不住谁——补上之后才真正参与判重。
"""

from django.db import migrations, models

from content.tier_rules import derive_tier


#: 打印认不出的记录时最多列几条，免得刷屏。总数照常打印。
_REPORT_LIMIT = 50


def backfill_tiers(apps, schema_editor):
    """按证书上的写法给历史记录认层级。认不出的留空并打印明细。"""
    Award = apps.get_model("content", "Award")

    updates = []
    unclassified = []
    for award in Award.objects.all().only("pk", "level", "title"):
        tier = derive_tier(award.level, award.title)
        if tier:
            updates.append(Award(pk=award.pk, tier=tier))
        else:
            unclassified.append((award.pk, award.level, award.title))

    Award.objects.bulk_update(updates, ["tier"], batch_size=500)
    print(
        f"content.award.tier.backfill: 回填 {len(updates)} 条，"
        f"认不出层级 {len(unclassified)} 条（空层级不参与判重，请人工在后台补）"
    )
    for pk, level, title in unclassified[:_REPORT_LIMIT]:
        print(f"  #{pk} level={level!r} title={title!r}")


class Migration(migrations.Migration):

    dependencies = [
        ("content", "0005_award_level_and_winners_required"),
    ]

    operations = [
        migrations.AlterField(
            model_name="award",
            name="level",
            field=models.CharField(max_length=100, verbose_name="证书上的级别写法"),
        ),
        migrations.AddField(
            model_name="award",
            name="tier",
            field=models.CharField(
                choices=[
                    ("national", "国家级"),
                    ("provincial", "省级"),
                    ("school", "校级"),
                ],
                default="",
                max_length=20,
                verbose_name="获奖层级",
            ),
            preserve_default=False,
        ),
        migrations.RunPython(backfill_tiers, migrations.RunPython.noop),
    ]
