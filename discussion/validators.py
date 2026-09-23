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
