"""模板标签：把当前页面换成另一种语言的地址，供顶栏语言切换使用。"""

from django import template
from django.urls import translate_url as django_translate_url


register = template.Library()


@register.simple_tag(takes_context=True)
def language_url(context, lang_code):
    """当前页面在 ``lang_code`` 语言下的地址（含查询串）。

    Django 只提供同名的 Python 函数（``django.urls.translate_url``），没有对应的
    模板标签，这里薄薄包一层。解析不出别的语言版本时返回原地址——顶栏宁可点了
    没反应，也不要给出一个不存在的链接；取不到 request 时返回空串，模板据此
    不渲染这个链接。
    """
    request = context.get("request")
    if request is None:
        return ""
    return django_translate_url(request.get_full_path(), lang_code)
