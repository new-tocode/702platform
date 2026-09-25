"""把受保护的上传件从公开的 mediafiles/ 搬进 protected_media/。

为什么需要它：过去项目书、批注版、归档版、帖子图、头像、个人图册都躺在
``MEDIA_ROOT`` 下，而 Nginx 把 ``/media/`` 直出那个目录——文件一旦落在那里，
谁拿到路径谁就能取。代码里那几处 ``FileResponse`` 前面明明有权限判定，却因为
还有另一条路（直接请求 ``/media/xxx``）而形同虚设。

两个根的**相对路径相同**，所以搬完之后数据库里的字段值一个字都不用改。这也是
它天然幂等的原因：重跑一次只会发现目标已存在。

**这条迁移会移动磁盘上的文件**，所以：

* 跑之前先备份（``deploy/backup.sh`` 已覆盖媒体目录）；
* 在停机窗口内执行——迁移期间若有请求正好在读文件，会取不到；
* 文件缺失（运维挪过、备份不完整）只记警告并跳过，不让整条迁移挂掉。

反向迁移把文件搬回 ``MEDIA_ROOT``，同样只搬不改名。
"""

import logging

from django.db import migrations

logger = logging.getLogger(__name__)


#: (app_label, 模型名, 字段名)。顺序无关紧要，但保持稳定便于对照。
PROTECTED_FILES = (
    ("accounts", "Profile", "avatar"),
    ("accounts", "GalleryImage", "image"),
    ("discussion", "PostImage", "image"),
    ("projects", "ProjectGroup", "proposal"),
    ("reviews", "ReviewTask", "annotated_file"),
    ("reviews", "ArchivedProposal", "file"),
)


def _rehome_all(apps, *, private):
    """把每个字段的每个文件在公开/受保护两个根之间搬一次。

    刻意不复用 ``core.storage.rehome``：迁移要冻结当时的行为，而 ``core.storage``
    会随代码演进（它现在读的是运行时 settings，将来可能换实现）。迁移里自己走一遍
    文件操作，这条迁移的语义就永远停在写下它的这一天。
    """
    from pathlib import Path

    from django.conf import settings

    origin_root = Path(settings.MEDIA_ROOT)
    target_root = Path(settings.PRIVATE_MEDIA_ROOT)

    moved = skipped = missing = 0
    for app_label, model_name, field_name in PROTECTED_FILES:
        model = apps.get_model(app_label, model_name)
        rows = model.objects.exclude(**{f"{field_name}": ""}).exclude(
            **{f"{field_name}__isnull": True}
        )
        for row in rows.iterator():
            file_field = getattr(row, field_name)
            name = getattr(file_field, "name", "")
            if not name:
                continue
            origin, destination = (
                (target_root / name, origin_root / name)
                if private
                else (origin_root / name, target_root / name)
            )
            if destination.exists():
                skipped += 1
                continue
            if not origin.exists():
                missing += 1
                logger.warning(
                    "private_media.missing model=%s.%s pk=%s path=%s",
                    app_label,
                    model_name,
                    row.pk,
                    origin,
                )
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            origin.rename(destination)
            moved += 1

    logger.info(
        "private_media.rehome moved=%s skipped=%s missing=%s private=%s",
        moved,
        skipped,
        missing,
        private,
    )


def move_into_private_root(apps, schema_editor):
    _rehome_all(apps, private=True)


def move_back_into_public_root(apps, schema_editor):
    _rehome_all(apps, private=False)


class Migration(migrations.Migration):
    dependencies = [
        # 必须显式依赖 core 自己的上一个迁移，否则 0001 与本条会变成 migration
        # graph 的两个叶子，manage.py 直接拒绝启动。
        ("core", "0001_initial"),
        ("accounts", "0013_alter_galleryimage_image_alter_profile_avatar"),
        ("discussion", "0006_alter_postimage_image"),
        ("projects", "0007_alter_projectgroup_proposal"),
        ("reviews", "0007_alter_archivedproposal_file_and_more"),
    ]

    operations = [
        migrations.RunPython(
            move_into_private_root,
            move_back_into_public_root,
        ),
    ]
