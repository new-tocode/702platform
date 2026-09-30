"""上传件的 SHA-256：算法本身，以及 mixin 什么时候重算、什么时候沿用。

mixin 的行为不依赖任何业务模型，所以这里用一个只存在于测试里的模型来测。
各业务模型「上传后指纹对不对」的端到端用例在各自 app 的测试里。
"""

import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, models
from django.test import SimpleTestCase, TestCase, override_settings

from core.hashing import CHUNK_SIZE, FileDigestMixin, sha256_of
from core.storage import private_storage


TEST_PRIVATE_MEDIA_ROOT = Path(
    tempfile.mkdtemp(prefix="competition-club-core-private-")
)


class ProbeFile(FileDigestMixin, models.Model):
    """只为测试而生：mixin 的行为不该被某个业务模型的字段牵着走。

    不写进任何 ``models.py``，所以 ``makemigrations`` 扫不到它，也就不进迁移。
    """

    digest_field = "attachment"
    attachment = models.FileField(upload_to="probe/", storage=private_storage, blank=True)
    label = models.CharField(max_length=20, blank=True)

    class Meta:
        app_label = "core"


class ProbeFileWithoutDigestField(FileDigestMixin, models.Model):
    """故意不声明 ``digest_field``：这个配置错误必须当场炸。

    它只会让指纹永远为空——不报错、不崩，只是那个字段静默地失效，而症状
    （「这个文件怎么没有校验值」）离原因很远。
    """

    attachment = models.FileField(upload_to="probe/", storage=private_storage, blank=True)

    class Meta:
        app_label = "core"


class Sha256OfTests(SimpleTestCase):
    """分块读的算法：结果与 hashlib 一致，且不把整份文件读进内存。"""

    def test_matches_hashlib(self):
        payload = b"the quick brown fox jumps over the lazy dog"
        self.assertEqual(
            sha256_of(ContentFile(payload)),
            hashlib.sha256(payload).hexdigest(),
        )

    def test_empty_file(self):
        self.assertEqual(
            sha256_of(ContentFile(b"")),
            hashlib.sha256(b"").hexdigest(),
        )

    def test_large_file_spanning_chunks(self):
        """跨过 CHUNK_SIZE 边界的内容一个字节都不能漏。

        分块读的经典错法是漏掉最后一块或首尾错位，小文件测不出来。
        """
        payload = bytes(range(256)) * (CHUNK_SIZE // 256 + 7)
        self.assertGreater(len(payload), CHUNK_SIZE)
        self.assertEqual(
            sha256_of(ContentFile(payload)),
            hashlib.sha256(payload).hexdigest(),
        )

    def test_reads_from_current_position(self):
        """从当前位置往后读——这是「调用方负责复位」的另一面。"""
        stream = ContentFile(b"XXXXXpayload")
        stream.seek(5)
        self.assertEqual(
            sha256_of(stream),
            hashlib.sha256(b"payload").hexdigest(),
        )


@override_settings(PRIVATE_MEDIA_ROOT=TEST_PRIVATE_MEDIA_ROOT)
class FileDigestMixinTests(TestCase):
    """什么时候重算、什么时候沿用。三种情形对应 _file_sha256 的三个分支。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # ProbeFile 不在任何迁移里，测试自己给它建表。建在 setUpClass 的事务
        # 里，tearDownClass 回滚时一并撤销，不用手工删。
        with connection.schema_editor() as editor:
            editor.create_model(ProbeFile)

    def test_missing_digest_field_fails_loudly(self):
        probe = ProbeFileWithoutDigestField()

        with self.assertRaises(ImproperlyConfigured):
            probe.save()

    def test_new_upload_is_hashed(self):
        probe = ProbeFile(label="x")
        probe.attachment = SimpleUploadedFile("a.bin", b"payload")
        self.assertEqual(
            probe._file_sha256(), hashlib.sha256(b"payload").hexdigest()
        )

    def test_upload_stream_survives_hashing(self):
        """算完指纹，上传流还要能被完整读出来。

        这是本功能最容易出的岔子：算哈希把指针读到末尾，紧接着的落盘读到
        空内容，于是磁盘上留下一个 0 字节的文件，而库里记着正确的大小和指纹。
        ``core.uploads`` 里 Pillow 的 ``close()`` 踩过同一个坑。
        """
        payload = b"x" * 4096
        probe = ProbeFile(label="x")
        probe.attachment = SimpleUploadedFile("a.bin", payload)
        probe._file_sha256()
        self.assertEqual(probe.attachment.read(), payload)

    def test_unchanged_file_keeps_existing_digest(self):
        """文件没换就不重算：改一句简介不该重读一遍 20 MB 的项目书。"""
        probe = ProbeFile(label="x")
        probe.attachment = SimpleUploadedFile("a.bin", b"first")
        probe.save()
        stored = probe.sha256
        probe.label = "y"
        with patch("core.hashing.sha256_of") as read_bytes:
            probe.save()
        read_bytes.assert_not_called()
        probe.refresh_from_db()
        self.assertEqual(probe.sha256, stored)
        self.assertEqual(stored, hashlib.sha256(b"first").hexdigest())

    def test_replaced_file_is_rehashed(self):
        probe = ProbeFile(label="x")
        probe.attachment = SimpleUploadedFile("a.bin", b"first")
        probe.save()
        probe.attachment = SimpleUploadedFile("b.bin", b"second")
        probe.save()
        self.assertEqual(probe.sha256, hashlib.sha256(b"second").hexdigest())

    def test_stored_file_without_digest_is_backfilled(self):
        """老数据：字段非空、指纹为空。从存储补算一次。"""
        name = private_storage.save("probe/old.bin", ContentFile(b"legacy"))
        probe = ProbeFile(label="x", attachment=name)
        self.assertEqual(probe.sha256, "")
        self.assertEqual(probe._file_sha256(), hashlib.sha256(b"legacy").hexdigest())

    def test_cleared_file_clears_digest(self):
        probe = ProbeFile(label="x")
        probe.attachment = SimpleUploadedFile("a.bin", b"payload")
        probe.save()
        probe.attachment = ""
        probe.save()
        self.assertEqual(probe.sha256, "")

    def test_missing_file_leaves_digest_empty(self):
        """库里指着、盘上没了：保存不该失败，但也不能编一个指纹出来。"""
        probe = ProbeFile(label="x", attachment="probe/gone.bin")
        with self.assertLogs("core.hashing", level="WARNING"):
            self.assertEqual(probe._file_sha256(), "")

    def test_update_fields_callers_still_persist_the_digest(self):
        """``save(update_fields=[…])`` 带了文件列、没带 sha256 时，指纹也要写进去。

        换头像走的正是 ``save(update_fields=["avatar", "updated_at"])``：
        指纹算出来了却不在写入列表里，库里就永远是空的，而内存里的值已经变了——
        下次保存会以为「没变」，再也不会重算。
        """
        probe = ProbeFile(label="x")
        probe.attachment = SimpleUploadedFile("a.bin", b"first")
        probe.save()
        probe.attachment = SimpleUploadedFile("b.bin", b"second")
        probe.save(update_fields=["attachment", "label"])
        probe.refresh_from_db()
        self.assertEqual(probe.sha256, hashlib.sha256(b"second").hexdigest())

    def test_update_fields_without_the_file_field_leaves_digest_alone(self):
        """文件列不在写入范围时，指纹保持原值——它得和库里的文件对得上。

        换文件却只写 ``label`` 是个自相矛盾的调用：Django 不会存这个新文件，
        库里指向的还是旧那份。指纹若跟着内存里的新内容走，就与文件对不上了。
        """
        probe = ProbeFile(label="x")
        probe.attachment = SimpleUploadedFile("a.bin", b"first")
        probe.save()
        probe.attachment = SimpleUploadedFile("b.bin", b"second")
        probe.save(update_fields=["label"])
        probe.refresh_from_db()
        self.assertEqual(probe.sha256, hashlib.sha256(b"first").hexdigest())

    def test_unchanged_digest_does_not_widen_update_fields(self):
        """指纹没变就别硬塞进 update_fields，免得每次保存都多写一列。"""
        probe = ProbeFile(label="x")
        probe.attachment = SimpleUploadedFile("a.bin", b"payload")
        probe.save()
        with patch.object(models.Model, "save") as parent_save:
            probe.save(update_fields=["attachment"])
        self.assertEqual(
            parent_save.call_args.kwargs["update_fields"], ["attachment"]
        )
