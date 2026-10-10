"""模板里安全地取文件地址。

``{{ field.url }}`` 是最自然的写法，但它在两种情况下都不是模板想要的：受保护的上传件
（``core/storage.py`` 的 ``PrivateStorage``）没有公开地址，``url()`` 返回**空串**；字段
本身为空时则直接抛 ``ValueError``。后者会让页面在渲染深处炸掉，排查起来很难受。

所以给模板一个不抛的入口：取不到地址时返回空串，让 ``{% if %}`` 能安静地判断。
护栏在别处——受保护件不在 ``mediafiles/`` 之下，Nginx 的 ``/media/`` 指不到它们。
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
