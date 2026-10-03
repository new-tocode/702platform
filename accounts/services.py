"""账号相关的写操作。

四件事：后台批量授予／撤销评审资格、后台批量增删用户组成员，以及个人信息页上的
头像与个人图册。资格与组员那两件要事务、要审计，所以不写在 admin 里——那里过去
改资格连审计都不留。

上传相关的写入口也收在这里，而不是散进视图：换头像、删图册都要连磁盘上的文件
一起处理，两件事得挨着做，而且不该让视图去碰存储层。
"""

from dataclasses import dataclass

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max, Sum
from django.utils.translation import gettext_lazy as _

from core.audit import record_audit
from core.storage import delete_stored_files

from .models import GALLERY_TOTAL_MAX_BYTES, GalleryImage, User
from .validators import validate_gallery_image


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


def set_group_members(*, group, members, actor, request=None):
    """把用户组的成员整份设成 ``members``，返回（新加入, 已移出）两份名单。

    后台的「组内用户」是个穿梭框：提交上来的是这个组**应有**的全部成员，所以这里
    做的是覆盖而不是增量。整份与现状比一次、只动真正变了的人——重复保存同一份名单
    既不写库也不留审计行（与 :func:`set_qualification` 同一条口径）。

    组成员关系决定内部通知投给谁（``Notice.visible_groups``），所以每次真正的变更
    都留一条审计：谁进来、谁出去。

    ``members`` 里的账号不必已经保存——传 ``User`` 实例即可。
    """
    wanted = {user.pk: user for user in members}
    with transaction.atomic():
        # 两个管理员同时保存同一个组时，不加锁就是各读各的现状、各写各的，最后拼出
        # 一份谁也没提交过的名单。锁在这一行上，两次保存排成队。
        Group.objects.select_for_update().get(pk=group.pk)
        current = set(group.user_set.values_list("pk", flat=True))
        added = [user for pk, user in wanted.items() if pk not in current]
        removed = list(User.objects.filter(pk__in=current - set(wanted)))
        if added:
            group.user_set.add(*added)
        if removed:
            group.user_set.remove(*removed)

    if not added and not removed:
        return (), ()

    record_audit(
        action="accounts.group.membership.update",
        user=actor,
        target=group,
        detail={
            "added": [user.get_username() for user in added],
            "removed": [user.get_username() for user in removed],
        },
        request=request,
    )
    return added, removed


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


@dataclass(frozen=True)
class GalleryBatchResult:
    """一次批量上传的结果：谁进了图册、谁没进、为什么，以及加完后的用量。

    ``rejected`` 与 ``overflowed`` 刻意分开：格式问题（不是图片、单张超限）要
    **逐张点名**，用户重选时才知道去掉哪几张；容量不足是同一件事发生了若干次，
    合成一条「还有 N 张没放下」，一次选二十张时不会刷出二十条提示。
    """

    added: tuple = ()
    #: ``(文件名, 原因)``，逐张。原因是可直接展示的译文。
    rejected: tuple = ()
    #: 因整册容量不足未加入的文件名。
    overflowed: tuple = ()
    #: 加完之后的合计用量，提示里的「已用 X MB」用它。
    used_bytes: int = 0


def add_gallery_images(*, profile, uploaded_files, actor, request=None):
    """往图册末尾批量加图，返回 :class:`GalleryBatchResult`。

    上限是「整册合计」而不是单张，所以要先求和再落盘；求和前锁住账号那一行：
    同一个人开两个标签页同时上传时，不加锁就会双双读到还没涨上去的用量、
    一起放行，合起来超限。锁加在账号上而不是个人资料上——配额是每人一份，
    口径与 ``GALLERY_TOTAL_MAX_BYTES`` 的名字一致。

    与单张时代不同的是**逐张判去留**：不是图片或单张超限的、合计会越过整册
    上限的，都跳过并记进结果，其余照加——一批里有几张不合格，不该拖累其余几张。
    单张校验放在这里而不是表单的校验器上，正因为校验器一遇错就中断整批、报不出
    「是哪几张」（见 ``accounts.forms.GalleryImageForm``）。

    审计仍是**每张成功入库的图一条**，与 ``accounts.gallery.delete`` 一张一条
    对称；被跳过的没有写操作，也就没有审计行。
    """
    uploads = list(uploaded_files or ())
    if not uploads:
        raise GalleryError(_("请选择要上传的图片。"))

    added, rejected, overflowed = [], [], []
    saved_files = []
    try:
        with transaction.atomic():
            User.objects.select_for_update().get(pk=profile.user_id)
            used = (
                GalleryImage.objects.filter(profile=profile).aggregate(
                    total=Sum("file_size")
                )["total"]
                or 0
            )
            last = GalleryImage.objects.filter(profile=profile).aggregate(
                last=Max("sort_order")
            )["last"]
            next_order = (last or 0) + 1

            for uploaded_file in uploads:
                try:
                    validate_gallery_image(uploaded_file)
                except ValidationError as exc:
                    rejected.append((uploaded_file.name, exc.messages[0]))
                    continue

                size = uploaded_file.size or 0
                if used + size > GALLERY_TOTAL_MAX_BYTES:
                    overflowed.append(uploaded_file.name)
                    continue

                image = GalleryImage(profile=profile, sort_order=next_order)
                image.image = uploaded_file
                try:
                    image.save()
                except Exception:
                    # 这一张写了一半（文件可能已经落盘）：先清掉再往上抛，
                    # 免得整个事务回滚之后，磁盘上留一份没人认领的文件。
                    if image.image and image.image._committed:
                        image.image.storage.delete(image.image.name)
                    raise
                saved_files.append((image.image.storage, image.image.name))

                record_audit(
                    action="accounts.gallery.add",
                    user=actor,
                    target=profile,
                    detail={"image_id": image.pk, "size": image.file_size},
                    request=request,
                )
                used += image.file_size
                next_order += 1
                added.append(image)
    except Exception:
        # 数据库回滚不会把已落盘的文件带回去，这里补上（与讨论区的多图帖子同一个
        # 手法，辅助函数已收口到 ``core.storage``）。
        delete_stored_files(saved_files)
        raise

    return GalleryBatchResult(
        added=tuple(added),
        rejected=tuple(rejected),
        overflowed=tuple(overflowed),
        used_bytes=used,
    )


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

    # 只改这一列，走 queryset 而不是 save()：模型的 save 会 full_clean 整行，
    # 换个排布还要把图片解码验一遍——白读一次盘，图片被运维挪走时更会直接报错。
    GalleryImage.objects.filter(pk=image.pk).update(layout=layout)
    image.layout = layout
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
