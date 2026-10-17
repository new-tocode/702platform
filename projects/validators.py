"""项目资料（压缩包）的上传校验。

压缩包怎么验住在 :mod:`core.uploads`；这里只把「给用户看的名字」与上限定下来——
字段、表单与 :data:`MATERIALS_HELP_TEXT` 共用这一份。
"""

from django.utils.translation import gettext_lazy as _

from core.uploads import validate_archive_upload


#: 项目资料的大小上限。与媒体库的视频同一档（500 MB），nginx 的
#: ``client_max_body_size 520m`` 对两者都留了余量——**改这里要同时看 deploy 的模板**。
MATERIALS_MAX_BYTES = 500 * 1024 * 1024

#: 项目资料的说明文案：模型字段与上传表单共用，改格式或上限时两处一起跟着变。
MATERIALS_HELP_TEXT = _(
    "支持 zip、7z、tgz；由项目组联系人维护，用于提交同行评审。"
)


def validate_materials_file(uploaded_file):
    """校验上传的项目资料压缩包。"""
    validate_archive_upload(
        uploaded_file,
        label=_("项目资料"),
        max_bytes=MATERIALS_MAX_BYTES,
    )


#: ``validate_proposal_file`` 的历史位置。项目书改叫项目资料时它跟着改名，但
#: **历史迁移按这个名字引用校验器**（``projects/0003``、``0007``、``reviews/0002``、
#: ``0006``、``0007``），Django 加载迁移时会来 import 它——删掉它 manage.py 直接
#: 起不来。所以留着这个别名，别再往任何字段上挂它。
validate_proposal_file = validate_materials_file
