"""获奖级别与获奖人改成必填。

两者各自撑着页面上的一个功能：级别是搜索与浏览时的分辨依据，获奖人是「我的获奖」
按姓名搜索、以及判重「同一批获奖人」的口径所依附的那一项。空着，这两件事就都做不成。

**这是一次只在校验层生效的改动**：``blank`` 管的是表单校验，不是数据库约束，两列本来
就是 NOT NULL（允许空串）。所以这条迁移不改表结构，也不会碰历史行——库里已经空着的
那几条继续空着，模板里 ``{% if award.level %}`` 一类的判断因此保留，判重也照旧把空值
当「这项不比」处理（见 ``content/similarity.py``）。
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("content", "0004_pg_trgm"),
    ]

    operations = [
        migrations.AlterField(
            model_name="award",
            name="level",
            field=models.CharField(max_length=100, verbose_name="获奖级别"),
        ),
        migrations.AlterField(
            model_name="award",
            name="winners",
            field=models.TextField(verbose_name="获奖人/团队"),
        ),
    ]
