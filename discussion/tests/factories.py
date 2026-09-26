"""造测试对象：两个临时媒体根、一张帖子配图。

这里只放跨模块共用的东西；各测试类自己的夹具（谁是成员、谁是管理员）留在它们的
``setUp`` 里。"""

from io import BytesIO
from pathlib import Path
import tempfile
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image


TEST_MEDIA_ROOT = Path(tempfile.mkdtemp(prefix="discussion-tests-"))
#: 受保护上传件的落盘根。与 TEST_MEDIA_ROOT 平级，见 accounts/tests.py 的说明。
TEST_PRIVATE_MEDIA_ROOT = Path(tempfile.mkdtemp(prefix="discussion-tests-private-"))


def png_upload(name="post.png", size=(10, 10)):
    stream = BytesIO()
    Image.new("RGB", size, color="#12508f").save(stream, format="PNG")
    return SimpleUploadedFile(name, stream.getvalue(), content_type="image/png")
