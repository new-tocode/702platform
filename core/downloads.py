"""受保护上传件的取件响应。

平台上有六个取件视图（头像、图册、帖子图、项目书、批注版、归档版），过去各写
各的 ``FileResponse``，于是同一件事写出了三种做法：有的接住了「文件不在盘上」
这一支、有的让它冒成 500；MIME 有的猜、有的不猜。给每个响应再加一次指纹头，就
是第六份逐字相同的代码——所以收到这里。

公开的媒体库不经过这里：它由 Nginx 直出 ``/media/``，本来就不该有权限判定
（见 ``core/storage.py`` 对两个根的说明）。
"""

import base64
import logging
import mimetypes

from django.http import FileResponse, Http404

from .hashing import DIGEST_LENGTH


logger = logging.getLogger(__name__)


def serve_file(file_field, *, download_name, as_attachment, sha256=""):
    """把一个存储里的文件送出去，并附上它的 SHA-256。

    ``file_field`` 是模型上的 FileField（``FieldFile``）。文件不在盘上时按 404
    处理而不是 500：运维挪过文件、备份恢复不完整都会走到这一支，那种情况下
    404 更贴切，也不会把路径写进错误页。

    ``sha256`` 是下载人要拿来比对的指纹。留空表示这份文件没有（图片类不给页面
    展示、历史文件还没回填），那就只发文件、不发头——但**不编一个值出来**：
    一个错的校验值比没有校验值更坏。
    """
    try:
        handle = file_field.open("rb")
    except FileNotFoundError as exc:
        raise Http404 from exc
    content_type = (
        mimetypes.guess_type(file_field.name)[0] or "application/octet-stream"
    )
    response = FileResponse(
        handle,
        as_attachment=as_attachment,
        filename=download_name,
        content_type=content_type,
    )
    _attach_digest(response, sha256)
    return response


def _attach_digest(response, sha256):
    """把校验值挂到响应头上。两个头，各有各的读者。

    * ``Content-Digest`` 是 RFC 9530 的标准写法，给按标准实现的客户端；
    * ``X-Checksum-SHA256`` 是十六进制，与 ``sha256sum``、``certutil -hashfile``
      的输出一字不差——下载的人把它粘进命令行就能比对，不必先做一次 base64
      解码。这是最可能被真正用到的那个。
    """
    if not sha256:
        return
    try:
        raw = bytes.fromhex(sha256)
    except (TypeError, ValueError):
        # 不该发生的输入不该让下载 500：文件明明取得到，却因为一个附加的头而
        # 下不成，是最坏的一种失败方式。留一条痕迹，然后只发文件。
        logger.warning("file_digest.invalid value=%r", sha256)
        return
    if len(raw) != DIGEST_LENGTH // 2:
        logger.warning("file_digest.unexpected_length value=%r", sha256)
        return
    response["Content-Digest"] = f"sha-256=:{base64.b64encode(raw).decode()}:"
    response["X-Checksum-SHA256"] = sha256
