"""上传文件的通用处理。

每个上传校验都绕不开两件事：按扩展名认类型、读完文件头再把指针拨回开头。
media 与 projects 两处 validators 各写过一遍、逐字相同，所以收到这里。

图片还有第三件事：确认它真是一张图（而不是改了扩展名的别的什么）。这段
原先只在 media 里有，头像与个人图册也要用，所以一并收进来——大小上限与
允许的扩展名是各调用方自己的口径（项目资料与评审回复 500 MB、头像 2 MB、
图册单张 5 MB），由调用方传进来，这里只管「怎么验」。

压缩包走同一套：:func:`validate_archive_upload` 收扩展名、大小、签名三道关，
名字（「项目资料」「评审回复」）与上限同样由调用方给。
"""

import io
from pathlib import Path

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from PIL import Image, UnidentifiedImageError


#: 一张图允许的像素总数。
#:
#: Pillow 自带的默认上限约 8948 万像素，且判定放在两处：超过一倍上限抛
#: ``DecompressionBombError``，超过半倍只是发一条 ``DecompressionBombWarning``。
#: 后者会让「声明 1 亿像素」的图通过校验、安然落盘，等页面渲染时才真正解码——
#: 受害的是每一个打开该页的人，而不是上传者自己。
#:
#: 6400 万像素（约 8000×8000）够任何头像、图册与配图，同时把上面那条缝堵上：
#: 阈值写在这里，下面的校验按它自己判，不再依赖 Pillow 的两档行为。
MAX_IMAGE_PIXELS = 64_000_000

#: **升级 Pillow 主版本时要确认** ``DecompressionBombError`` 与 ``Image.MAX_IMAGE_PIXELS``
#: 都还在、语义没变——下面这一整套防护建立在它们之上（全量测试里有专门的用例）。

#: 平台接受的图片扩展名：媒体库、头像、个人图册共用这一份。
IMAGE_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "webp", "gif"})

#: 平台接受的压缩包扩展名。写成元组而不是集合：顺序即报错文案里的顺序
#: （zip 最常见，排在最前），集合的遍历顺序读起来是随机的。
ARCHIVE_EXTENSIONS = ("zip", "7z", "tgz")

#: 各压缩包格式开头的魔数。tar.gz 与 tgz 是同一件东西，只是叫法不同；
#: 这里只认 .tgz（口径见 :data:`ARCHIVE_EXTENSIONS`）。
_ARCHIVE_SIGNATURES = {
    "zip": (b"PK", _("文件不是有效的 zip。")),
    "7z": (b"7z\xbc\xaf\x27\x1c", _("文件不是有效的 7z。")),
    "tgz": (b"\x1f\x8b", _("文件不是有效的 tgz。")),
}


def file_extension(name):
    """文件名的扩展名：小写、不带点；没有扩展名时返回空串。"""
    return Path(name or "").suffix.lower().lstrip(".")


def reset_file_position(uploaded_file):
    """把上传文件的读指针拨回开头。

    不支持 seek 的对象（内存里的文件、测试替身）安静跳过——它们本来就在开头。
    """
    try:
        uploaded_file.seek(0)
    except (AttributeError, OSError):
        return


def _validate_image_content(uploaded_file):
    """按二进制内容验一张图，顺便把「这不是图片」与「这是解压炸弹」都挡下。

    两件事都在这里做，因为它们都必须赶在图片对象被销毁之前：

    * **解压炸弹**。``Image.open()`` 只读文件头，读完尺寸就判定，超限抛
      ``DecompressionBombError``。这个异常必须在当场接住——它的基类是
      ``Exception`` 而不是 ``OSError``，漏出去就是一个未捕获异常，一个几十字节
      的文件即可让视图报 500（复核见安全检查报告 V1 条；那份报告含生产标识，不入版本库）。
    * **尺寸上限**。Pillow 只在「超过它自己上限一倍」时才抛异常，介于半倍与
      一倍之间的图发一条 ``DecompressionBombWarning`` 就放行，落盘后要等到页面
      渲染时才真正解码——受害的是每一个打开该页的人。这里按
      :data:`MAX_IMAGE_PIXELS` 统一判，不依赖 Pillow 那两档行为。

    **读的是副本，不是调用方的流。** Pillow 的 ``verify()`` 与 ``close()` 都会把
    底层文件关掉（``ImageFile._close_fp`` 关的正是我们传进去的那个对象），而上传
    文件在校验之后还要被存起来、还要被 ``reset_file_position`` 拨回开头。让它关掉
    一个归它自己的 BytesIO，上传文件就始终可用。
    """
    reset_file_position(uploaded_file)
    try:
        content = uploaded_file.read()
    except (AttributeError, OSError, ValueError):
        content = None
    reset_file_position(uploaded_file)
    # 拿不到内容（测试替身一类的对象）就退回原流，按老样子验。
    source = io.BytesIO(content) if content is not None else uploaded_file

    try:
        image = Image.open(source)
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValidationError(_("上传文件不是有效的图片。")) from exc

    try:
        width, height = image.size
        if width * height > MAX_IMAGE_PIXELS:
            raise ValidationError(
                _("图片过大（%(width)s×%(height)s 像素），请压缩后再上传。")
                % {"width": width, "height": height}
            )
        image.verify()
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValidationError(_("上传文件不是有效的图片。")) from exc
    finally:
        image.close()


def validate_image_upload(uploaded_file, *, label, max_bytes, extensions=IMAGE_EXTENSIONS):
    """校验一张上传的图片：扩展名、大小、MIME 家族与真实的图片签名。

    ``label`` 是文案里给用户看的名字（如「头像」），``max_bytes`` 是调用方
    自己的大小上限。不合格一律抛 :class:`ValidationError`，消息可直接展示。
    """
    if not uploaded_file:
        raise ValidationError(_("请选择要上传的图片。"))

    extension = file_extension(uploaded_file.name)
    if extension not in extensions:
        allowed = "、".join(sorted(extensions))
        raise ValidationError(
            _("%(label)s仅支持 %(allowed)s 格式。")
            % {"label": label, "allowed": allowed}
        )
    if uploaded_file.size and uploaded_file.size > max_bytes:
        raise ValidationError(
            _("%(label)s不能超过 %(limit)s MB。")
            % {"label": label, "limit": max_bytes // (1024 * 1024)}
        )

    content_type = (
        getattr(uploaded_file, "content_type", "")
        or getattr(getattr(uploaded_file, "file", None), "content_type", "")
        or ""
    )
    if content_type and not content_type.startswith("image/"):
        raise ValidationError(_("文件类型与图片不符，请确认选的是图片。"))

    # 扩展名与 MIME 都是自报的，最后按二进制内容验一次。读的是副本，所以
    # 校验完上传文件仍然可用——阶段 4 的统一 uuid 落盘还要再读它一遍。
    _validate_image_content(uploaded_file)


def validate_archive_upload(uploaded_file, *, label, max_bytes):
    """校验一个上传的压缩包：扩展名、大小与文件签名。

    与 :func:`validate_image_upload` 同一形状，区别只有两处：压缩包没有 MIME 家族
    可判（浏览器对 .7z 常报 application/octet-stream，按 MIME 拦会拦掉合法的上传），
    以及扩展名清单全平台只有一份（:data:`ARCHIVE_EXTENSIONS`）——项目资料与评审回复
    收的就是同一套格式。

    ``label`` 是文案里给用户看的名字（「项目资料」「评审回复」），``max_bytes`` 是
    调用方自己的上限。不合格一律抛 :class:`ValidationError`，消息可直接展示。
    """
    if not uploaded_file:
        raise ValidationError(_("请选择要上传的文件。"))

    extension = file_extension(uploaded_file.name)
    if extension not in ARCHIVE_EXTENSIONS:
        raise ValidationError(
            _("%(label)s仅支持 %(allowed)s 格式。")
            % {"label": label, "allowed": "、".join(ARCHIVE_EXTENSIONS)}
        )
    if uploaded_file.size and uploaded_file.size > max_bytes:
        raise ValidationError(
            _("%(label)s不能超过 %(limit)s MB。")
            % {"label": label, "limit": max_bytes // (1024 * 1024)}
        )

    prefix, message = _ARCHIVE_SIGNATURES[extension]
    reset_file_position(uploaded_file)
    header = uploaded_file.read(len(prefix))
    reset_file_position(uploaded_file)
    if not header.startswith(prefix):
        raise ValidationError(message)
