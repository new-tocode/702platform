"""模板过滤器：把文件路径拆成模板真正想显示的两部分。"""

import os

from django import template


register = template.Library()


@register.filter
def basename(value):
    """返回路径中的文件名。"""
    return os.path.basename(str(value or ""))


@register.filter
def file_ext(value):
    """返回大写扩展名，用于文件类型角标；无扩展名时返回 FILE。"""
    name = basename(value)
    if "." not in name:
        return "FILE"
    return name.rsplit(".", 1)[-1].upper()
