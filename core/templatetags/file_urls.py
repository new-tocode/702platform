"""模板里安全地取文件地址。

``{{ field.url }}`` 是最自然的写法，但受保护的上传件没有公开地址——它们的存储
刻意让 ``url()`` 抛异常，好让任何绕开视图拼地址的尝试在开发期就暴露（见
``core/storage.py``）。两种需求都对，冲突出在模板上：模板要的是「有就渲染成链接、
没有就渲染成文本」，而抛异常会让页面在渲染深处炸掉，排查起来很难受。

所以给模板一个不抛的入口：取不到地址时返回空串，让 ``{% if %}`` 能安静地判断。
护栏仍在 Python 那一侧——视图里拼地址照样当场失败。
"""

from django import template


register = template.Library()


@register.filter
def file_url(value):
    """文件字段的公开地址；受保护文件（或空字段）返回空串。"""
    try:
        return value.url
    except (ValueError, AttributeError, NotImplementedError):
        return ""
