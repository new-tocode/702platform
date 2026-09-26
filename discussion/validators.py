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
    """帖子图片的落盘名：随机名，不带用户信息。

    历史迁移（0004/0006）引用这个名字，所以函数留着；**新上传不走它**——
    现在统一用 ``core.storage.neutral_upload_to``，命名口径与其余受保护上传件
    相同，且落盘根换成了 ``PRIVATE_MEDIA_ROOT``。
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
