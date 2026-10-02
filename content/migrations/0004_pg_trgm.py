"""装上 pg_trgm：获奖记录的判重要用它算相似度（见 content/similarity.py）。

为什么值得动数据库扩展，而不是在 Python 里比字符串：判重是逐字段算相似度，
把这一步放在库里，候选集就留在库里——年份筛完之后只算那几条，不必把整年的记录
拉进进程再逐条比。

**先确认扩展在不在**：pg_trgm 是 contrib 扩展，但**不随 PostgreSQL server 包一起
装**——PGDG 的 RPM 把它放在 postgresql<主版本>-contrib 里，Debian 系在
postgresql-contrib 里。只装了 server 的机器上 ``CREATE EXTENSION`` 会报
"extension pg_trgm is not available"（找不到 ``pg_trgm.control``）。装上 contrib 包
即可，不需要重启 PostgreSQL；``deploy/deploy.sh`` 与 ``deploy/install.sh`` 在
migrate 前会先探一次并给出安装命令。

**建不出来的话**：pg_trgm 自 PostgreSQL 13 起是 trusted 扩展，库的属主就能建；
``deploy/install.sh`` 建的库正是以应用角色为属主（``createdb -O "$DJANGO_DB_USER"``），
所以扩展在位时这一步不会因权限失败。真遇到权限被收走的库，用超级用户执行一次
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
