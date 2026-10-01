"""跨应用共用的表单件。

``MultipleImageField`` 原先是社团空间的私有件。历年获奖也要「一次选几张图」，
两个应用各留一份的话，「多文件字段」就有了两个定义，改一处忘一处只是时间问题，
所以收到这里——与 ``core/storage.py`` 收口 ``ProtectedClearableFileInput``、
``core/downloads.py`` 收口取件响应同一个理由。

字段只管「收下若干个文件」，**类型与大小是调用方自己的口径**：由各表单把校验器
传进来（讨论区 3 MB、获奖图片 10 MB）。这里不预设任何业务规则。
"""

from django import forms


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.FileField):
    """一个字段收多个文件，``cleaned_data`` 里是列表而不是单个文件。"""

    widget = MultipleFileInput

    def clean(self, data, initial=None):
        if data in self.empty_values:
            return []
        uploads = data if isinstance(data, (list, tuple)) else [data]
        # 逐个交给父类：每个文件各自走一遍 validators，报错也是逐个报。
        return [
            super(MultipleImageField, self).clean(upload, initial) for upload in uploads
        ]
