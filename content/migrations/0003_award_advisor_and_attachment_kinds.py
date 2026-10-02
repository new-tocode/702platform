"""Award 加指导老师，附件分成「获奖证书」与「参赛图片」两类。

原先一个 ``attachments`` 混装奖状、现场图与视频：页面上分不开，打包下载时也挑不出
证书。拆成两个 M2M 之后，历史附件要有个去处——

* **图片 → 获奖证书**。历年获奖里的图片绝大多数就是奖状扫描件，划进证书这一边，
  老记录也能被「打包下载」选中；判断错了的，管理员在后台两栏之间拖一下即可。
* **视频 → 参赛图片**。视频不可能是证书，而且 ``certificates`` 在模型上限定只收
  图片，留在证书那一栏会让后台表单存不回去。

复制走的是历史模型，所以这一步必须排在 ``RemoveField`` 之前：``attachments`` 一删，
中间表就没了，数据也无从搬起。反方向不做还原——回滚会把两个新中间表整个删掉，
把两边硬合回一个字段只会丢信息。
"""

from django.db import migrations, models


def split_attachments(apps, schema_editor):
    Award = apps.get_model("content", "Award")
    for award in Award.objects.prefetch_related("attachments"):
        certificates = []
        photos = []
        for media in award.attachments.all():
            if media.kind == "image":
                certificates.append(media.pk)
            else:
                photos.append(media.pk)
        if certificates:
            award.certificates.add(*certificates)
        if photos:
            award.photos.add(*photos)


class Migration(migrations.Migration):

    dependencies = [
        ("content", "0002_homeslide"),
        ("media", "0002_mediafile_sha256"),
    ]

    operations = [
        migrations.AddField(
            model_name="award",
            name="advisor",
            field=models.CharField(blank=True, max_length=200, verbose_name="指导老师"),
        ),
        migrations.AddField(
            model_name="award",
            name="certificates",
            field=models.ManyToManyField(
                blank=True,
                limit_choices_to={"kind": "image"},
                related_name="certificate_awards",
                to="media.mediafile",
                verbose_name="获奖证书",
            ),
        ),
        migrations.AddField(
            model_name="award",
            name="photos",
            field=models.ManyToManyField(
                blank=True,
                related_name="photo_awards",
                to="media.mediafile",
                verbose_name="参赛图片",
            ),
        ),
        migrations.RunPython(split_attachments, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="award",
            name="attachments",
        ),
    ]
