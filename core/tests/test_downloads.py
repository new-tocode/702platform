"""取件响应：指纹头挂得对，且「文件不在盘上」是 404 而不是 500。"""

import base64
import hashlib
import shutil
import tempfile
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.http import Http404
from django.test import SimpleTestCase

from core.downloads import serve_file


class _StoredFile:
    """一个够用的 ``FieldFile`` 替身。

    ``serve_file`` 只碰三样东西：``open()``、``name`` 和 ``storage``。用真模型
    反而要把整张表拖进来，而这里被测的是响应怎么拼，不是文件怎么落盘。
    """

    def __init__(self, storage, name):
        self.storage = storage
        self.name = name

    def open(self, mode):
        return self.storage.open(self.name, mode)


class ServeFileTests(SimpleTestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="competition-club-downloads-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.storage = FileSystemStorage(location=self.root)
        self.payload = b"the bytes a downloader will check"
        self.name = self.storage.save("probe.bin", ContentFile(self.payload))
        self.digest = hashlib.sha256(self.payload).hexdigest()

    def _response(self, **kwargs):
        kwargs.setdefault("download_name", "probe.bin")
        kwargs.setdefault("as_attachment", True)
        return serve_file(_StoredFile(self.storage, self.name), **kwargs)

    def test_digest_travels_in_both_header_spellings(self):
        response = self._response(sha256=self.digest)

        # 十六进制那份与 sha256sum 的输出一字不差，是最可能被真正用到的。
        self.assertEqual(response["X-Checksum-SHA256"], self.digest)
        # 标准那份按 RFC 9530 写成结构化字段的字节串（base64，冒号包裹）。
        self.assertEqual(
            response["Content-Digest"],
            "sha-256=:%s:" % base64.b64encode(bytes.fromhex(self.digest)).decode(),
        )

    def test_body_is_the_file_and_nothing_else(self):
        """头是对的，身子也得是原样的字节——校验值只对得上原文件才有意义。"""
        response = self._response(sha256=self.digest)

        self.assertEqual(b"".join(response.streaming_content), self.payload)

    def test_no_digest_means_no_headers(self):
        """没有指纹就只发文件。图片类走的就是这一支。"""
        response = self._response()

        self.assertNotIn("X-Checksum-SHA256", response)
        self.assertNotIn("Content-Digest", response)

    def test_malformed_digest_is_skipped_rather_than_fatal(self):
        """畸形的指纹不该让下载 500。

        文件明明取得到，却因为一个附加的头而下不成，是最坏的一种失败方式：
        用户看到的是「下载坏了」，而真正的问题在一个他看不见的字段上。
        """
        for value in ("not-hex", "abcd", "", None, 12345):
            with self.subTest(value=value):
                response = self._response(sha256=value)
                self.assertNotIn("X-Checksum-SHA256", response)
                self.assertEqual(
                    b"".join(response.streaming_content), self.payload
                )

    def test_missing_file_is_a_404(self):
        """运维挪过文件、备份不完整都会走到这一支；500 会把路径写进错误页。"""
        missing = _StoredFile(self.storage, "does-not-exist.bin")

        with self.assertRaises(Http404):
            serve_file(missing, download_name="x.bin", as_attachment=True)

    def test_content_type_follows_the_stored_name(self):
        name = self.storage.save("probe.pdf", ContentFile(b"%PDF-1.4 stub"))

        response = serve_file(
            _StoredFile(self.storage, name),
            download_name="项目书.pdf",
            as_attachment=True,
        )

        self.assertEqual(response["Content-Type"], "application/pdf")

    def test_attachment_flag_reaches_content_disposition(self):
        inline = self._response(as_attachment=False)
        attached = self._response(as_attachment=True)

        self.assertTrue(inline["Content-Disposition"].startswith("inline"))
        self.assertTrue(attached["Content-Disposition"].startswith("attachment"))
