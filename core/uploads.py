"""上传文件的通用处理。

每个上传校验都绕不开两件事：按扩展名认类型、读完文件头再把指针拨回开头。
media 与 projects 两处 validators 各写过一遍、逐字相同，所以收到这里。

图片还有第三件事：确认它真是一张图（而不是改了扩展名的别的什么）。这段
原先只在 media 里有，头像与个人图册也要用，所以一并收进来——大小上限与
允许的扩展名是各调用方自己的口径（项目书 20 MB、头像 2 MB、图册单张 5 MB），
由调用方传进来，这里只管「怎么验」。
"""

from pathlib import Path

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from PIL import Image, UnidentifiedImageError


#: 平台接受的图片扩展名：媒体库、头像、个人图册共用这一份。
IMAGE_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "webp", "gif"})


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

    # 扩展名与 MIME 都是自报的，最后按二进制内容验一次。
    reset_file_position(uploaded_file)
    try:
        with Image.open(uploaded_file) as image:
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValidationError(_("上传文件不是有效的图片。")) from exc
    finally:
        reset_file_position(uploaded_file)
