import re

from django.core.exceptions import ValidationError
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


def validate_post_image(uploaded_file):
    from core.uploads import validate_image_upload

    validate_image_upload(
        uploaded_file,
        label=_("帖子图片"),
        max_bytes=POST_IMAGE_MAX_BYTES,
    )
