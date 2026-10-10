"""上传件的 SHA-256 指纹。

平台上的文件要能校对：上传时算一份指纹存下来，下载的人拿它比对，就能确认
到手的字节与当初上传的一模一样。项目书、批注版这类要送审、要归档的文档尤其
需要——它们是评审结论的依据，而文件在传递途中被换掉不该无声无息。

指纹按**存储里的字节**算，与文件名、路径都无关——受保护件的落盘名已被换成
uuid（见 ``core/storage.py``），公开件（媒体库）却保留原文件名，而两种情况下
指纹都只认字节。所以指纹是文件**内容**的身份。
"""

import hashlib
import logging

from django.core.exceptions import ImproperlyConfigured
from django.db import models

from .uploads import reset_file_position


logger = logging.getLogger(__name__)

#: 读文件的块大小。500 MB 的视频上限决定了不能整份读进内存。
CHUNK_SIZE = 1024 * 1024

#: 十六进制 SHA-256 摘要的字符数。
DIGEST_LENGTH = 64


def sha256_of(file_obj):
    """算一个已打开文件的 SHA-256，返回小写十六进制。

    分块读而不是一次 ``read()``：媒体库的视频上限 500 MB，整份读进来就是
    500 MB 的内存峰值，而上传本可以只占一个块的常驻内存。
    """
    digest = hashlib.sha256()
    while True:
        chunk = file_obj.read(CHUNK_SIZE)
        if not chunk:
            break
        digest.update(chunk)
    return digest.hexdigest()


class FileDigestMixin(models.Model):
    """带一个文件字段的模型：每次保存时让指纹跟上文件。

    指纹存在模型自己身上，而不是单开一张按文件名索引的旁表。理由是文件会
    **跟着记录一起死**：换头像要删旧图、删图册要删盘、帖子图随编辑被替换
    （``accounts.services`` / ``discussion.services``）。旁表在这些路径上都会
    留下没人清理的孤儿行，而字段跟着行走——删记录即删指纹，天生一致，也不
    需要额外的清理任务。

    只认一个文件字段：平台上每个模型都只有一个。真有第二个的时候再把字段名
    变成参数，不必现在就为它铺路。
    """

    class Meta:
        abstract = True

    #: 要计算指纹的文件字段名。子类必须指定。
    digest_field = ""

    # 小写十六进制。不给 help_text：editable=False 的字段不进任何表单，写了也
    # 没有地方显示——想说明它是什么，说明写在上面那段 docstring 里。
    sha256 = models.CharField(
        "SHA-256",
        max_length=DIGEST_LENGTH,
        blank=True,
        editable=False,
    )

    def save(self, *args, **kwargs):
        if not self.digest_field:
            # 忘了声明只会让指纹永远为空——不报错、不崩，只是这个字段静默地
            # 失效。宁可当场炸在开发者面前。
            raise ImproperlyConfigured(
                f"{type(self).__name__} 继承了 FileDigestMixin，却没有声明 "
                f"digest_field。"
            )
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and self.digest_field not in update_fields:
            # 文件这一列根本不在写入范围里。Django 因此不会调用 FileField 的
            # pre_save，文件不落盘、库里指向的还是原来那份——指纹也就不该动。
            # 此时若照着内存里那个从未存过的文件重算，指纹就会与库里的文件
            # 对不上号，而这正是本功能要防的事。
            super().save(*args, **kwargs)
            return
        digest = self._file_sha256()
        if digest != self.sha256:
            self.sha256 = digest
            if update_fields is not None:
                # 调用方指明了只写哪几列，指纹不在其中就写不进库，而内存里的
                # 值已经变了——下次保存会以为「没变」而不再算。换头像走的正是
                # ``save(update_fields=["avatar", "updated_at"])``。
                kwargs["update_fields"] = set(update_fields) | {"sha256"}
        super().save(*args, **kwargs)

    def _file_sha256(self):
        """当前文件字段该有的指纹；没有文件就是空串。

        三种情形各有各的算法，因为「读哪儿」不一样：

        * **刚上传、还没落盘**（``_committed`` 为假）：读的就是上传流本身。
          文件此刻还在临时文件里，写完再读一遍最终文件等于把同一份内容读两次。
        * **已落盘、已有指纹**：文件没换过，沿用。改一句简介不该重读一遍
          20 MB 的项目书。
        * **已落盘、指纹为空**：迁移之前的老数据。补算一次，此后一直沿用。
        """
        field_file = getattr(self, self.digest_field)
        if not field_file:
            return ""
        if not getattr(field_file, "_committed", True):
            # 读完必须拨回开头，否则紧接着的落盘会存下一个空文件——Pillow 的
            # ``close()`` 在 core/uploads.py 里已经教过这一课。
            reset_file_position(field_file)
            digest = sha256_of(field_file)
            reset_file_position(field_file)
            return digest
        if self.sha256:
            return self.sha256
        try:
            with field_file.storage.open(field_file.name, "rb") as handle:
                return sha256_of(handle)
        except FileNotFoundError:
            # 库里指着、盘上没了。保存本身不该因此失败（可能只是改一句简介），
            # 但必须留痕：文件对不上号是运维要知道的事。
            logger.warning(
                "file_digest.missing model=%s pk=%s name=%s",
                type(self).__name__,
                self.pk,
                field_file.name,
            )
            return ""
