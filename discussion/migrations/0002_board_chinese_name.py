from django.db import migrations, models


def use_english_name_as_legacy_label(apps, schema_editor):
    Board = apps.get_model("discussion", "Board")
    Board.objects.using(schema_editor.connection.alias).update(
        name_zh=models.F("name")
    )


class Migration(migrations.Migration):
    dependencies = [
        ("discussion", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="board",
            name="name_zh",
            field=models.CharField(
                blank=True,
                default="",
                max_length=80,
                verbose_name="中文名称",
            ),
        ),
        migrations.RunPython(
            use_english_name_as_legacy_label,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="board",
            name="name_zh",
            field=models.CharField(max_length=80, verbose_name="中文名称"),
        ),
        migrations.AlterModelOptions(
            name="board",
            options={
                "ordering": ("name_zh", "name", "pk"),
                "verbose_name": "社团空间板块",
                "verbose_name_plural": "社团空间板块",
            },
        ),
    ]
