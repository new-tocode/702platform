"""造测试对象：两个临时媒体根，与几种上传件。

这里只放**跨模块共用**的东西。各测试类自己的夹具（谁是管理员、谁是成员）刻意
留在它们的 ``setUp`` 里——见 :mod:`accounts.tests` 的说明。
"""

import os
import tempfile
from io import BytesIO
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image


TEST_MEDIA_ROOT = Path(tempfile.mkdtemp(prefix="competition-club-accounts-"))
#: 受保护上传件的落盘根。**与 TEST_MEDIA_ROOT 平级、不是它的子目录**——两者
#: 的分离正是被测的性质之一（受保护文件不在公开根下），做成子目录会让那条断言
#: 失去意义。清理时两个都要删。
TEST_PRIVATE_MEDIA_ROOT = Path(tempfile.mkdtemp(prefix="competition-club-accounts-private-"))


def png_upload(name="avatar.png", size=(8, 8)):
    stream = BytesIO()
    Image.new("RGB", size, color="#12508f").save(stream, format="PNG")
    return SimpleUploadedFile(name, stream.getvalue(), content_type="image/png")


def oversized_png_upload(name="huge.png", megabytes=3):
    """一张真图、真超限：随机噪点压不动，尺寸按需要的 MB 数放大。"""
    pixels_per_side = int((megabytes * 1024 * 1024 / 3) ** 0.5) + 100
    stream = BytesIO()
    raw = os.urandom(pixels_per_side * pixels_per_side * 3)
    Image.frombytes("RGB", (pixels_per_side, pixels_per_side), raw).save(
        stream, format="PNG"
    )
    return SimpleUploadedFile(name, stream.getvalue(), content_type="image/png")
