"""模板过滤器：把文件路径拆成模板真正想显示的两部分。"""

import os

from django import template

from core.uploads import file_extension


register = template.Library()


@register.filter
def basename(value):
    """返回路径中的文件名。"""
    return os.path.basename(str(value or ""))


@register.filter
def file_ext(value):
    """返回大写扩展名，用于文件类型角标；无扩展名时返回 FILE。

    口径与上传校验、落盘名共用一份（``core.uploads.file_extension``）：``.tar.gz``
    因此显示成 ``TAR.GZ`` 而不是 ``GZ``。
    """
    extension = file_extension(basename(value))
    return extension.upper() if extension else "FILE"
