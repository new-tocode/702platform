"""个人信息页上传件的校验。

头像与图册图像都只是「图片 + 各自的大小上限」：验什么住在
:mod:`core.uploads`，这里只把上限与给用户看的名字定下来，字段、表单与文案
共用这一份。
"""

from django.utils.translation import gettext_lazy as _

from core.uploads import validate_image_upload


#: 头像的大小上限：够一张清楚的证件照，又不至于让每个页面都拖着几 MB 的图走。
AVATAR_MAX_BYTES = 2 * 1024 * 1024

#: 头像的说明文案：模型字段与上传表单共用，改上限时两处一起跟着变。
AVATAR_HELP_TEXT = _("不超过 %(limit)s MB。") % {
    "limit": AVATAR_MAX_BYTES // (1024 * 1024)
}

#: 图册单张的大小上限。整册的合计上限在 ``accounts.models``：那条要跨行求和的
#: 约束落在服务层，口径跟着模型走。
GALLERY_IMAGE_MAX_BYTES = 5 * 1024 * 1024

#: 图册单张的说明文案。
GALLERY_HELP_TEXT = _("不超过 %(limit)s MB。") % {
    "limit": GALLERY_IMAGE_MAX_BYTES // (1024 * 1024)
}


def validate_avatar(uploaded_file):
    """校验上传的头像图片。"""
    validate_image_upload(
        uploaded_file,
        label=_("头像"),
        max_bytes=AVATAR_MAX_BYTES,
    )


def validate_gallery_image(uploaded_file):
    """校验图册里的一张图。"""
    validate_image_upload(
        uploaded_file,
        label=_("图册图像"),
        max_bytes=GALLERY_IMAGE_MAX_BYTES,
    )
