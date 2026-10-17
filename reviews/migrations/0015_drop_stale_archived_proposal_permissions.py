"""删掉模型改名留下的四条僵尸权限。

``RenameModel`` 把 content type 就地改了名（``archivedproposal`` → ``archivedreply``），
但 ``auth_permission`` 里那四行的 codename 还写着旧模型名。于是后台的权限选择器里
会同时列出「Can add archived reply」与「Can add archived proposal」，后者谁也点不到
——没有任何代码认它，拿着它的账号也多不出一点权限。

``remove_stale_contenttypes`` 清不掉它：那个命令只删「模型已经不存在的 content
type」，而这里 content type 还在、只是换了名字（那一步的坑见
docs/更新维护/开发与部署.md 的部署注意事项）。

全新库不受影响：权限行是 ``post_migrate`` 按最终模型状态建的，那时只有新 codename，
这条迁移是空跑。
"""

from django.db import migrations


#: 改名前的四个 codename，逐条写死：它们不再由任何模型生成，只能在这里认出来。
STALE_CODENAMES = (
    "add_archivedproposal",
    "change_archivedproposal",
    "delete_archivedproposal",
    "view_archivedproposal",
)


def drop_stale_permissions(apps, schema_editor):
    """按 codename 删；只认 reviews 这个应用，免得误伤别的应用里同名的东西。

    用户与用户组持有它们的记录由外键级联一起走——那些授权本来就指向不存在的动作。
    """
    Permission = apps.get_model("auth", "Permission")
    Permission.objects.filter(
        content_type__app_label="reviews",
        codename__in=STALE_CODENAMES,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("reviews", "0014_alter_reviewtask_reply_file"),
    ]

    operations = [
        # 反向不重建：旧 codename 是历史留下的垃圾，回退这次改名时也没有理由把它请回来。
        migrations.RunPython(drop_stale_permissions, migrations.RunPython.noop),
    ]
