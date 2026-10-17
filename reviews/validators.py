"""评审回复（压缩包）的上传校验。

与项目资料是同一套格式与校验（都在 :mod:`core.uploads`），差别只有文案里的名字：
校验器按调用方给的 ``label`` 说话，所以「评审回复」这几个字留在本模块，不写进
``projects``——评审侧的东西不归项目组模块命名。
"""

from django.utils.translation import gettext_lazy as _

from core.uploads import validate_archive_upload


#: 评审回复的大小上限，与项目资料同一档（500 MB）。
REPLY_MAX_BYTES = 500 * 1024 * 1024

#: 评审回复的说明文案：模型字段与评审表单共用。
#:
#: 「请勿在文件属性中保留可识别个人身份的信息」这句不是客套：平台只保证落盘名与
#: 下载头里不含身份，压缩包**内部**的文件名与属性平台看不到也改不了，而评审对
#: 项目组匿名是这一块的硬约束。
REPLY_HELP_TEXT = _(
    "选填；支持 zip、7z、tgz。请勿在文件属性中保留可识别个人身份的信息。"
)


def validate_reply_file(uploaded_file):
    """校验上传的评审回复压缩包。"""
    validate_archive_upload(
        uploaded_file,
        label=_("评审回复"),
        max_bytes=REPLY_MAX_BYTES,
    )
