"""成员从前台传的获奖图片。

校验本身复用 ``core.uploads.validate_image_upload``（扩展名、大小、MIME、真实的
图片签名，含解压炸弹那一档），这里只给两件事：

* **文案**。上限与格式的说法由 ``core.uploads`` 用 ``label`` 拼出来，而那边的
  默认标签是中文硬编码（媒体库只在后台用，后台不在双语范围内）。前台的英文界面
  需要这两个词有译文，所以标签由这里传进去。
* **张数**。图片本身没毛病、只是太多，这一条只有调用方知道，所以在表单里判
  （见 ``content.forms``），这里只放上限本身。
"""

from django.utils.translation import gettext_lazy as _

from core.uploads import validate_image_upload
from media.validators import IMAGE_MAX_BYTES


#: 一条记录里每类图片最多几张。证书与参赛图片各算各的。
IMAGE_LIMIT = 5

#: 单张上限直接取媒体库那一份：这些图上传后进的就是媒体库，两边不一致只会让
#: 「后台能传、前台不能传」这种怪事出现。
MAX_IMAGE_BYTES = IMAGE_MAX_BYTES

#: 上面那个数换成 MB，给表单的提示语用——提示里写死「10 MB」的话，
#: 上限一改，话就成了假的。
MAX_IMAGE_MB = MAX_IMAGE_BYTES // (1024 * 1024)


def validate_certificate(uploaded_file):
    validate_image_upload(
        uploaded_file, label=_("获奖证书"), max_bytes=MAX_IMAGE_BYTES
    )


def validate_photo(uploaded_file):
    validate_image_upload(uploaded_file, label=_("参赛图片"), max_bytes=MAX_IMAGE_BYTES)
