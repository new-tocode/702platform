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
from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from core.downloads import serve_file

from .models import GalleryImage, Profile


logger = logging.getLogger(__name__)


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
    # 头像与图册是页面上的图，不是给人下载的件：指纹照算、照存库，但不随响应
    # 发出去——校验值是给「下载下来要核对」的文档准备的。
    return serve_file(
        profile_obj.avatar,
        download_name=f"avatar{extension}",
        as_attachment=False,
    )


@login_required
@require_GET
def gallery_file(request, pk):
    """个人图册里的一张图。图册是个人主页上给成员看的那一块，登录即可取。"""
    image = get_object_or_404(GalleryImage, pk=pk)
    extension = Path(image.image.name).suffix.lower()
    return serve_file(
        image.image,
        download_name=f"gallery{extension}",
        as_attachment=False,
    )
