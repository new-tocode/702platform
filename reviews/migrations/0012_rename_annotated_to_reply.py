from django.db import migrations


class Migration(migrations.Migration):
    """批注版项目书改叫评审回复：字段与归档模型一起改名。

    两处都必须走 rename（``RenameField`` / ``RenameModel``）——写成删旧建新，
    存量的评审回复与归档记录会连同文件一起从库里消失。
    """

    dependencies = [
        ("reviews", "0011_delete_reviewerleave"),
    ]

    operations = [
        migrations.RenameField(
            model_name="reviewtask",
            old_name="annotated_file",
            new_name="reply_file",
        ),
        migrations.RenameModel(
            old_name="ArchivedProposal",
            new_name="ArchivedReply",
        ),
    ]
