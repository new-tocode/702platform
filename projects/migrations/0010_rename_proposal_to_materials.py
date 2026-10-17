from django.db import migrations


class Migration(migrations.Migration):
    """项目书改叫项目资料，字段跟着改名。

    必须是 ``RenameField``：写成「删掉 proposal、加一个 materials」会把存量项目资料
    的**行内值清空**（文件本身还在盘上，但谁也找不到它了）。``makemigrations`` 交互式
    问的那句就是这一步，这里直接写死，免得下次谁再生成一遍又选错。
    """

    dependencies = [
        ("projects", "0009_projectgroup_sha256"),
    ]

    operations = [
        migrations.RenameField(
            model_name="projectgroup",
            old_name="proposal",
            new_name="materials",
        ),
    ]
