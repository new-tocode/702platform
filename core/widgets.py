"""跨 app 共用的表单控件。

这里只放「前端脚本按标记接管」的那种控件；控件本身不决定渲染结果——Markdown
预览的内容由服务端的 ``content.templatetags.rendering.render_markdown`` 生成，
前端只负责把结果贴到面板里。
"""

from django import forms
from django.utils.translation import gettext as _


class MarkdownPreviewTextarea(forms.Textarea):
    """带「预览」标记的 textarea。

    标记与文案只在 ``render()`` 时写进属性，**不要挪到 ``__init__`` 或表单类的
    ``Meta.widgets``**：那里是导入期，惰性译文会按当时的语言定型，英文界面会
    显示中文（见 ``AGENTS.md`` §4 的「惰性译文」）。

    控件不改 DOM 结构：按钮与预览面板由 ``static/js/markdown_preview.js`` 插到
    textarea 前后。这样 ``mentions.js`` 依赖的 ``textarea.parentElement`` 仍是
    原来的字段容器，@ 补全菜单的定位不会跟着变。
    """

    def render(self, name, value, attrs=None, renderer=None):
        attrs = {
            **(attrs or {}),
            "data-markdown-preview": "1",
            "data-preview-label": _("预览"),
            "data-preview-hide-label": _("收起预览"),
            "data-preview-empty": _("没有可预览的内容。"),
            "data-preview-error": _("预览生成失败，请稍后再试。"),
        }
        return super().render(name, value, attrs, renderer)

    class Media:
        # 前台由 base.html 统一加载；后台没有 base.html，交给 admin 的
        # form.media 按需带出来（只有用到本控件的页面才会加载）。
        js = ("js/markdown_preview.js",)
