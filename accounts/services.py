"""账号相关的写操作。

三件事：后台批量授予／撤销评审资格，以及个人信息页上的头像与个人图册。资格那件
要事务、要审计，所以不写在 admin 里——那里过去改资格连审计都不留。

上传相关的写入口也收在这里，而不是散进视图：换头像、删图册都要连磁盘上的文件
一起处理，两件事得挨着做，而且不该让视图去碰存储层。
"""

from django.db import transaction
from django.db.models import Max, Sum
from django.utils.translation import gettext_lazy as _

from core.audit import record_audit

from .models import GALLERY_TOTAL_MAX_BYTES, GalleryImage, User


class GalleryError(Exception):
    """图册的领域异常（配额一类的规矩），由视图翻成页面上的提示。"""


#: 允许批量改的资格字段。
#:
#: 刻意不含 ``is_superuser`` 与 ``is_active``：那两个是账号本身的状态，
#: 该在用户编辑页逐个确认，被一次批量动作改掉太危险。
QUALIFICATION_FLAGS = ("is_reviewer", "is_preliminary_reviewer", "is_super_reviewer")


def set_qualification(*, users, flag, value, actor, request=None):
    """批量授予或撤销一项评审资格，返回真正发生变化的账号数。

    ``flag`` 是 ``accounts.User`` 上的布尔字段名，只接受
    :data:`QUALIFICATION_FLAGS` 里的那几个。取值已经相同的账号会被跳过，
    所以重复提交是幂等的，审计里也只记这次真正动了谁。

    资格是布尔字段而不是一张关联表——判定那边（``reviews.permissions``）
    读的就是这些字段，这里只是它们唯一的写入口。
    """
    if flag not in QUALIFICATION_FLAGS:
        raise ValueError(f"{flag} 不是可以批量授予的资格字段。")

    targets = [user for user in users if getattr(user, flag) != value]
    if not targets:
        return 0

    with transaction.atomic():
        for user in targets:
            setattr(user, flag, value)
        User.objects.bulk_update(targets, [flag])

    record_audit(
        action=(
            "accounts.qualification.grant" if value else "accounts.qualification.revoke"
        ),
        user=actor,
        detail={
            "flag": flag,
            "user_ids": [user.pk for user in targets],
            "usernames": [user.get_username() for user in targets],
        },
        request=request,
    )
    return len(targets)


def set_avatar(*, profile, uploaded_file, actor, request=None):
    """换头像：新图先落盘，再把旧图从磁盘上删掉。

    ``profile`` 要是**数据库里那一份**（视图取出来的实例即可）：本函数先读
    ``profile.avatar`` 记下旧文件，才把新文件盖上去——实例若已被表单改过，
    这里读到的就是新图，删旧文件会变成删新文件。
    """
    previous_name = profile.avatar.name if profile.avatar else ""
    previous_storage = profile.avatar.storage if profile.avatar else None

    with transaction.atomic():
        profile.avatar = uploaded_file
        profile.save(update_fields=["avatar", "updated_at"])
        record_audit(
            action="accounts.avatar.update",
            user=actor,
            target=profile,
            detail={"replaced": bool(previous_name)},
            request=request,
        )

    # 文件系统不在事务里，所以删除放在提交之后：万一前面出错，顶多多留一个旧文件，
    # 不会出现「库里还指着这张图、磁盘上已经没了」。
    if previous_name:
        previous_storage.delete(previous_name)
    return profile


def clear_avatar(*, profile, actor, request=None):
    """删头像：清空字段并删掉文件；本来就没有头像时什么也不做。"""
    if not profile.avatar:
        return False
    name, storage = profile.avatar.name, profile.avatar.storage

    with transaction.atomic():
        profile.avatar = ""
        profile.save(update_fields=["avatar", "updated_at"])
        record_audit(
            action="accounts.avatar.clear",
            user=actor,
            target=profile,
            detail={},
            request=request,
        )

    storage.delete(name)
    return True


def add_gallery_image(*, profile, uploaded_file, actor, request=None):
    """往图册末尾加一张图；超过整册上限时抛 :class:`GalleryError`。

    上限是「合计」而不是单张，所以要先求和再落盘。求和前锁住账号那一行：
    同一个人开两个标签页同时上传时，不加锁就会双双读到还没涨上去的用量、
    一起放行，合起来超限。锁加在账号上而不是个人资料上——配额是每人一份，
    口径与 ``GALLERY_TOTAL_MAX_BYTES`` 的名字一致。
    """
    size = uploaded_file.size or 0

    with transaction.atomic():
        User.objects.select_for_update().get(pk=profile.user_id)
        used = (
            GalleryImage.objects.filter(profile=profile).aggregate(
                total=Sum("file_size")
            )["total"]
            or 0
        )
        if used + size > GALLERY_TOTAL_MAX_BYTES:
            raise GalleryError(
                _("图册合计不能超过 %(limit)s MB，当前已用 %(used)s MB。")
                % {
                    "limit": GALLERY_TOTAL_MAX_BYTES // (1024 * 1024),
                    "used": round(used / (1024 * 1024), 1),
                }
            )

        last = GalleryImage.objects.filter(profile=profile).aggregate(
            last=Max("sort_order")
        )["last"]
        image = GalleryImage(profile=profile, sort_order=(last or 0) + 1)
        image.image = uploaded_file
        image.save()

        record_audit(
            action="accounts.gallery.add",
            user=actor,
            target=profile,
            detail={"image_id": image.pk, "size": image.file_size},
            request=request,
        )
    return image


def move_gallery_image(*, image, direction, actor, request=None):
    """把一张图上移或下移一位；已在头／尾时原地不动，返回是否真的动了。

    顺序按 ``(sort_order, id)`` 排定，移动后在事务里整段重排成 0..n-1：只交换
    相邻两张的 ``sort_order`` 在两张撞号时看不出变化，重排则顺带把编号收紧。

    ``direction`` 只认 ``"up"`` 与 ``"down"``，其余取值是编程错误。
    """
    if direction not in ("up", "down"):
        raise ValueError(f"{direction} 不是可用的移动方向。")

    siblings = list(
        GalleryImage.objects.filter(profile_id=image.profile_id).order_by(
            "sort_order", "id"
        )
    )
    index = next(
        position for position, item in enumerate(siblings) if item.pk == image.pk
    )
    target = index - 1 if direction == "up" else index + 1
    if not 0 <= target < len(siblings):
        return False

    siblings[index], siblings[target] = siblings[target], siblings[index]
    with transaction.atomic():
        for position, item in enumerate(siblings):
            item.sort_order = position
        GalleryImage.objects.bulk_update(siblings, ["sort_order"])

    record_audit(
        action="accounts.gallery.reorder",
        user=actor,
        target=image,
        detail={"direction": direction, "from": index, "to": target},
        request=request,
    )
    return True


def set_gallery_layout(*, image, layout, actor, request=None):
    """改一张图的排布（普通／大图／整行）。取值没变时什么也不做。"""
    if layout not in {choice for choice, _label in GalleryImage.LAYOUT_CHOICES}:
        raise ValueError(f"{layout} 不是可用的排布。")
    if image.layout == layout:
        return image

    image.layout = layout
    image.save(update_fields=["layout"])
    record_audit(
        action="accounts.gallery.layout",
        user=actor,
        target=image,
        detail={"layout": layout},
        request=request,
    )
    return image


def delete_gallery_image(*, image, actor, request=None):
    """删掉一张图，连磁盘上的文件一起。"""
    name, storage = image.image.name, image.image.storage
    image_id, file_size, profile = image.pk, image.file_size, image.profile

    with transaction.atomic():
        image.delete()
        record_audit(
            action="accounts.gallery.delete",
            user=actor,
            target=profile,
            detail={"image_id": image_id, "size": file_size},
            request=request,
        )

    # 文件系统不在事务里，删除放在提交之后（与头像同一条理由）。
    storage.delete(name)
