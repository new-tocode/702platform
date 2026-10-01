"""把若干条获奖记录的证书收成一个 zip。

一次「我的获奖」可能横跨十几条记录、几十个文件，逐张另存太费事，所以由服务端
打包。几处取舍：

* **写临时文件，不攒内存。** 选中的证书加起来可能几百 MB，先攒在内存里再一次性
  发出去，就是拿进程的内存换用户的等待。临时文件由 ``TemporaryFile`` 管，响应
  发完即随对象回收。
* **ZIP_STORED，不压缩。** 证书是 JPEG/PNG，本身就是压缩格式，Deflate 再走一遍
  几乎不减小体积，只是白烧 CPU。
* **重名加序号。** 同一个奖的几张证书常常同名（``证书.jpg``），而 zip 里的条目
  名是唯一的，后面的会盖掉前面的。
* **文件不在盘上就跳过。** 运维挪过文件、备份恢复不完整都会走到这一支；一条记录
  缺张图，不该让整包下不成——跳过几个、装进几个，由调用方告诉用户。

包里只有证书，没有参赛图片：这是「下载获奖证书」这个动作的字面意思，也是
``Award.certificates`` 与 ``photos`` 分开的理由。
"""

import logging
from pathlib import Path
import re
import shutil
import tempfile
from typing import NamedTuple
import zipfile

from django.utils import timezone
from django.utils.translation import gettext as _


logger = logging.getLogger(__name__)


#: 一次最多打包多少条记录。``award`` 是 POST 参数，条数由请求方说了算；不设上限
#: 的话，一次请求就足以把磁盘塞满。
MAX_ARCHIVE_AWARDS = 100

#: zip 条目名里不能出现的字符：路径分隔符与 Windows 的保留字符，外加控制字符。
_UNSAFE_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

#: 条目名里留给奖项名称的长度。整条路径太长在 Windows 上解不开。
_MAX_STEM = 80


def build_certificate_archive(awards):
    """把 ``awards`` 的证书打进一个 zip，返回 :class:`CertificateArchive`。

    ``awards`` 是一个已经取好的序列（不是 QuerySet）：调用方在视图里查、这里只管
    打包，也就不会在写 zip 的过程中又去碰一次库。
    """
    archive = tempfile.TemporaryFile()
    used_names = set()
    packed = 0
    missing = 0
    try:
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as bundle:
            for award in awards:
                # 先开文件、后编号：序号要落在真正装进包里的那几张上，否则少一张图
                # 就会出现「只有一个 -2.png」这种没头没尾的名字。
                available = []
                for media in award.certificates.all():
                    try:
                        available.append((media, media.file.open("rb")))
                    except FileNotFoundError:
                        missing += 1
                        logger.warning(
                            "content.awards.archive.missing media_id=%s award_id=%s",
                            media.pk,
                            award.pk,
                        )
                try:
                    for index, (media, handle) in enumerate(available, start=1):
                        entry = _entry_name(
                            award, media, index, len(available), used_names
                        )
                        with handle, bundle.open(entry, "w") as target:
                            shutil.copyfileobj(handle, target, 1024 * 1024)
                        packed += 1
                finally:
                    # 打包途中出错时，还没轮到的那几个句柄也得关掉。循环变量不叫
                    # `_`：它会把本模块的 gettext 短名遮蔽成局部变量。
                    for _media, handle in available:
                        handle.close()
    except Exception:
        archive.close()
        raise
    archive.seek(0)
    return CertificateArchive(
        file=archive,
        filename=_("获奖证书_%(date)s.zip")
        % {"date": timezone.localdate().isoformat()},
        packed=packed,
        missing=missing,
    )


class CertificateArchive(NamedTuple):
    """打包结果：一个已倒回开头的临时文件，以及这次打包的实情。"""

    file: object  # tempfile.TemporaryFile() 的返回值，响应发完随对象回收
    filename: str
    packed: int  # 真正装进去的文件数
    missing: int  # 记录里有、盘上却不在的文件数


def _entry_name(award, media, index, total, used_names):
    """给一张证书取个看得懂、又不重名的条目名：``2024-数学建模一等奖.jpg``。

    一个奖有多张证书时才补 ``-1``、``-2``：只有一张时那个数字没有信息量。
    重名（不同奖项同名、或同一张图挂了两条记录）往后顺延序号。
    """
    suffix = Path(media.file.name).suffix.lower() or ".jpg"
    stem = _UNSAFE_NAME.sub("_", f"{award.year}-{award.title}").strip() or "award"
    if total > 1:
        stem = f"{stem}-{index}"
    stem = stem[:_MAX_STEM]

    name = f"{stem}{suffix}"
    serial = 2
    while name in used_names:
        name = f"{stem}({serial}){suffix}"
        serial += 1
    used_names.add(name)
    return name
