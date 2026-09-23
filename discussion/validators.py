import re
from pathlib import Path
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


_BOARD_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 &()'/_-]{0,79}$")


def clean_board_name(value):
    name = (value or "").strip()
    if not name or not _BOARD_NAME.fullmatch(name):
        raise ValidationError(
            _("板块名称需为 1 至 80 个字符的英文名称，可包含数字、空格和常见标点。")
        )
    return name


_CHINESE_BOARD_NAME = re.compile(r".*[\u3400-\u9fff].*", re.DOTALL)


def clean_chinese_board_name(value):
    name = (value or "").strip()
    if not name or len(name) > 80 or not _CHINESE_BOARD_NAME.fullmatch(name):
        raise ValidationError(_("请输入 1 至 80 个字符且包含中文的板块名。"))
    return name


POST_IMAGE_MAX_BYTES = 3 * 1024 * 1024
POST_IMAGE_LIMIT = 3


def post_image_upload_to(instance, filename):
    """帖子图片落盘用随机名：原文件名可能带个人信息，也免得重名互相覆盖。

    ``upload_to`` 是函数时 Django 原样采用返回值，不再做 strftime，所以日期目录
    要在这里自己算出来——写成 ``%Y`` 会真的落一个叫 ``%Y`` 的目录。
    """
    return (
        f"discussion/{timezone.now():%Y/%m}/"
        f"{uuid4().hex}{Path(filename).suffix.lower()}"
    )


def validate_post_image(uploaded_file):
    from core.uploads import validate_image_upload

    validate_image_upload(
        uploaded_file,
        label=_("帖子图片"),
        max_bytes=POST_IMAGE_MAX_BYTES,
    )
