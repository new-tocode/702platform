"""受保护上传件的取件视图（账号侧）。

头像与个人图册的可见性来自业务规则（它们只出现在登录后的页面），而 Nginx 的
``/media/`` 是直出的：文件一旦落在那里，谁拿到路径谁就能取。所以这两类文件放在
``PRIVATE_MEDIA_ROOT``（见 ``core/storage.py``），只能从这里出去。

门槛是「已登录」而不是「已改密」：刚拿到初始口令的人进不了任何成员页面，也就
不需要看到头像；而社团空间的成员名单（登录即可进）要显示头像。取「已登录」
正好对上实际能到达这些页面的范围。

项目书、批注版、帖子图的取件不在本模块：它们各自还有别的判据，住在自己的应用里
（``projects.views`` / ``reviews.views`` / ``discussion.views``）。
"""

import logging
import mimetypes
from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from .models import GalleryImage, Profile


logger = logging.getLogger(__name__)


def protected_file_response(file_field, *, download_name):
    """把受保护存储里的文件送出去。

    文件不在盘上时按 404 处理而不是 500：运维挪过文件、备份恢复不完整都会走到
    这一支，那种情况下 404 更贴切，也不会把路径写进错误页。
    """
    try:
        handle = file_field.open("rb")
    except FileNotFoundError as exc:
        raise Http404 from exc
    content_type = (
        mimetypes.guess_type(file_field.name)[0] or "application/octet-stream"
    )
    return FileResponse(
        handle,
        as_attachment=False,
        filename=download_name,
        content_type=content_type,
    )


@login_required
@require_GET
def avatar_file(request, user_id):
    """某个成员的头像。"""
    profile_obj = get_object_or_404(
        Profile.objects.select_related("user"),
        user_id=user_id,
    )
    if not profile_obj.avatar:
        raise Http404
    extension = Path(profile_obj.avatar.name).suffix.lower()
    return protected_file_response(
        profile_obj.avatar, download_name=f"avatar{extension}"
    )


@login_required
@require_GET
def gallery_file(request, pk):
    """个人图册里的一张图。图册是个人主页上给成员看的那一块，登录即可取。"""
    image = get_object_or_404(GalleryImage, pk=pk)
    extension = Path(image.image.name).suffix.lower()
    return protected_file_response(
        image.image, download_name=f"gallery{extension}"
    )
