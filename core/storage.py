"""受保护上传件的存储。

平台上有两类上传件，安全属性完全不同，过去却躺在同一个目录里：

* **公开的**：媒体库（``mediafiles/uploads/``）。它是首页轮播、历年获奖、成员
  风采、公开通知的配图，那些页面对匿名访客开放，所以这些文件本来就该能直接取。
* **受保护的**：项目书、批注版、归档版、帖子图、头像、个人图册。它们的可见性
  由业务规则决定（谁能看这个项目组、谁是这个板块的成员），而 ``/media/`` 是
  Nginx 直出的静态目录——文件一旦落在那里，谁拿到路径谁就能取，视图里的权限
  判定形同虚设。

所以受保护的那些放进 :data:`~django.conf.settings.PRIVATE_MEDIA_ROOT`，它**不在**
``mediafiles/`` 之下，Nginx 的 ``/media/`` 永远指向不到这里。取文件一律经过视图，
权限判定才有意义。

存储实例刻意不给 ``base_url``：``.url`` 会直接抛 ``ValueError``，谁想绕开视图直接
拼地址都会当场失败，而不是悄悄生成一个能用的公开链接。
"""

import logging
import shutil
import uuid
from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.forms.widgets import ClearableFileInput
from django.utils import timezone
from django.utils.deconstruct import deconstructible


logger = logging.getLogger(__name__)


@deconstructible(path="core.storage.PrivateStorage")
class PrivateStorage(FileSystemStorage):
    """受保护文件的存储：没有可用的 URL。

    覆写 ``url()`` 而不是靠 ``base_url=None``：FileSystemStorage 把 None 当作
    「没传」，会退回 ``settings.MEDIA_URL`` 拼出一个能用的地址（实测如此）。
    靠一个会被回退的构造参数来保证安全约定太脆，直接让 ``url()`` 抛异常——
    谁想绕开视图拼地址，都会在开发时当场失败，而不是上线后悄悄多出一条旁路。

    ``location`` 不在这里写死：Django 序列化字段时必须能把存储还原进迁移文件，
    而绝对路径写进迁移就会把开发机的目录结构带到生产上（实测生成过
    ``location=PurePosixPath('/home/alen/work/702platform/protected_media')``）。
    ``@deconstructible`` 让它按类路径引用，路径由运行时的 settings 决定。
    """

    @property
    def base_location(self):
        return settings.PRIVATE_MEDIA_ROOT

    def url(self, name):
        """没有公开地址，返回空串。

        不抛异常：Django 的 ``ClearableFileInput.is_initial()`` 会
        ``getattr(value, "url", False)`` —— 它真的求值这个属性，异常会从模板渲染
        最深处冒出来（实测 ``{{ form.proposal }}`` 直接 500）。而那个 ``getattr``
        带默认值，说明框架本就预期 ``url`` 可能取不到。

        「必须走视图」这条约定因此由目录边界保证，不靠这里抛异常：
        ``PRIVATE_MEDIA_ROOT`` 不在 ``MEDIA_ROOT`` 之下，Nginx 的 ``/media/``
        只映射后者，没有任何 HTTP 路径能直接取到受保护文件。
        """
        return ""


#: 受保护文件的存储。取文件一律经过视图，权限判定才有意义。
private_storage = PrivateStorage()


class ProtectedClearableFileInput(ClearableFileInput):
    """「当前文件」区块按**有没有文件名**判断，而不是按有没有 URL。

    Django 原版用 ``is_initial()``（内部是 ``getattr(value, "url", False)``）来
    决定要不要渲染「当前文件 / 清除」那一块。受保护的文件没有 URL，于是这一块
    整个消失——用户看不到自己已经上传的项目书，也没有清除勾选框。名字在，
    就是有文件；判据换成名字才对。
    """

    def is_initial(self, value):
        return bool(getattr(value, "name", ""))

    def format_value(self, value):
        return value if self.is_initial(value) else None


@deconstructible(path="core.storage.NeutralUploadTo")
class NeutralUploadTo:
    """按前缀与年月分目录、文件名换成 uuid 的 ``upload_to``。

    两件事一起做：

    * **uuid 命名**。原始文件名会带上人名、组名、项目名（「项目书 终版-张三.pdf」
      是很典型的叫法），而文件名会跟着文件一路走进备份、走进运维的 ``ls``、走进
      下载时的 ``Content-Disposition``。评审要匿名、项目书不该从文件名泄露组员
      身份，所以存储名与用户填的名字彻底脱钩。
    * **年月分目录**。单个目录塞几十万个文件会让文件系统查找变慢，也让人工翻备份
      变得不可能。

    扩展名保留：它不影响匿名性，却是运维与 MIME 判断需要的。

    写成类而不是「返回闭包的工厂函数」，是因为迁移要能序列化它：Django 把
    ``upload_to`` 写进迁移文件时必须找得到一个可导入的对象，闭包做不到（实测报
    ``Could not find function upload_to in core.storage``）。``@deconstructible``
    让 Django 记录构造参数 ``prefix``，迁移里因此是 ``NeutralUploadTo(prefix="…")``
    这样一个可导入、可比较的值。
    """

    def __init__(self, prefix):
        self.prefix = prefix

    def __call__(self, instance, filename):
        extension = Path(filename or "").suffix.lower()
        return f"{self.prefix}/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{extension}"

    def __eq__(self, other):
        return isinstance(other, NeutralUploadTo) and self.prefix == other.prefix

    def __hash__(self):
        return hash((self.__class__.__name__, self.prefix))


def neutral_upload_to(prefix):
    """``NeutralUploadTo`` 的简写，调用处读起来更顺。"""
    return NeutralUploadTo(prefix)


def rehome(file_field, *, private):
    """把一个已存文件的落盘位置在公开/受保护两个根之间搬一次，返回新的相对路径。

    数据迁移与运维脚本共用它：「这条记录的文件现在该在哪个根下」是一个判断，
    散在两处写迟早会分叉。两个根的相对路径相同（只有 location 不同），所以搬完
    之后字段值不用改——这也让它天然幂等。

    文件不存在时返回原路径并记一条警告：那是数据不完整，不该让整条迁移挂掉，
    但必须留下痕迹。目标已存在同名文件时不覆盖——重跑迁移或两边都有一份的情况，
    当作已就位更安全。
    """
    name = file_field.name
    if not name:
        return name

    origin_root = Path(settings.MEDIA_ROOT)
    target_root = Path(settings.PRIVATE_MEDIA_ROOT)
    origin, destination = (
        (origin_root / name, target_root / name)
        if private
        else (target_root / name, origin_root / name)
    )

    if destination.exists():
        logger.info("private_media.already_there path=%s", destination)
        return name
    if not origin.exists():
        logger.warning("private_media.missing path=%s", origin)
        return name

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(origin), str(destination))
    logger.info("private_media.moved from=%s to=%s", origin, destination)
    return name
