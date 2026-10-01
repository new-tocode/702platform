"""装上 pg_trgm：获奖记录的判重要用它算相似度（见 content/similarity.py）。

为什么值得动数据库扩展，而不是在 Python 里比字符串：判重是逐字段算相似度，
把这一步放在库里，候选集就留在库里——年份筛完之后只算那几条，不必把整年的记录
拉进进程再逐条比。pg_trgm 是 PostgreSQL 的 contrib 扩展，随服务端一起装好，
不需要额外软件包。

**建不出来的话**：pg_trgm 自 PostgreSQL 13 起是 trusted 扩展，库的属主就能建；
``deploy/install.sh`` 建的库正是以应用角色为属主（``createdb -O "$DJANGO_DB_USER"``），
所以正常路径下这一步不会失败。真遇到权限被收走的库，用超级用户执行一次
``CREATE EXTENSION pg_trgm;`` 再重跑迁移即可（见 docs/deploy.md）。
"""

from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("content", "0003_award_advisor_and_attachment_kinds"),
    ]

    operations = [
        TrigramExtension(),
    ]
