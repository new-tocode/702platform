"""项目书的 SHA-256 指纹。

新加的列此刻是空的，而运行时的规则是「文件没换就沿用」——老记录不会自己保存，
指纹就一直空着。所以这条迁移主动补一遍，读一遍盘把值算出来。

哈希的算法与分块写死在本文件里，不复用 ``core.hashing``：同 core 0002 的理由，
迁移要冻结当时的行为，而运行时那份会随代码演进。
"""

import hashlib
import logging

from django.db import migrations, models


logger = logging.getLogger(__name__)

#: 读文件的块大小。
CHUNK_SIZE = 1024 * 1024


def _sha256(field_file):
    with field_file.storage.open(field_file.name, "rb") as handle:
        digest = hashlib.sha256()
        while True:
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def backfill(apps, schema_editor):
    model = apps.get_model("projects", "ProjectGroup")
    rows = model.objects.exclude(proposal="").filter(sha256="")
    for row in rows.iterator():
        try:
            digest = _sha256(row.proposal)
        except FileNotFoundError:
            # 库里指着、盘上没了。回填不该因此中断，但这行的指纹会一直空着。
            logger.warning(
                "file_digest.backfill.missing model=projects.ProjectGroup pk=%s name=%s",
                row.pk,
                row.proposal.name,
            )
            continue
        model.objects.filter(pk=row.pk).update(sha256=digest)


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0008_alter_groupcreaterequest_description_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="projectgroup",
            name="sha256",
            field=models.CharField(
                blank=True, editable=False, max_length=64, verbose_name="SHA-256"
            ),
        ),
        # 反向交给 RemoveField：列都要没了，值留着没有意义。
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
