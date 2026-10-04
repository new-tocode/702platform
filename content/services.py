"""历年获奖的写操作：事务边界、审计、领域异常都在这里。

视图只负责取表单、调这里、把结果翻译成页面上的话。
"""

import logging

from django.db import connection, transaction

from core.audit import record_audit
from media.models import MediaFile

from .models import Award
from .similarity import find_similar_award, identity_key


logger = logging.getLogger(__name__)


class DuplicateAward(Exception):
    """已经有一条同样的获奖记录。带着那一条，好让页面把它指出来。"""

    def __init__(self, existing):
        super().__init__(f"duplicate of award #{existing.pk}")
        self.existing = existing


@transaction.atomic
def create_award(
    *,
    title,
    competition,
    year,
    tier="",
    level="",
    winners="",
    advisor="",
    certificates=(),
    photos=(),
    uploader,
    request=None,
):
    """新建一条获奖记录，并把成员上传的图片收进媒体库。

    判重与写入在同一个事务里，中间还夹一把咨询锁（advisory lock）：两个人同时
    提交同一条记录时，双方的判重都会在对方写入之前跑完，两条就一起进库了。
    要锁的那一行此刻还不存在，`select_for_update` 锁不住不存在的东西，所以锁的是
    **这条记录的身份**（归一化之后的串），事务结束自动释放。哈希撞车只会让两个
    不相干的记录排队，不影响正确性。
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            [
                identity_key(
                    competition=competition,
                    title=title,
                    level=level,
                    year=year,
                    winners=winners,
                )
            ],
        )

    existing = find_similar_award(
        competition=competition, title=title, level=level, year=year, winners=winners
    )
    if existing is not None:
        logger.info(
            "content.award.create.duplicate title=%s year=%s existing_id=%s user=%s",
            title,
            year,
            existing.pk,
            uploader.get_username(),
            extra={"request_id": getattr(request, "request_id", "-")},
        )
        raise DuplicateAward(existing)

    award = Award.objects.create(
        title=title,
        competition=competition,
        year=year,
        tier=tier,
        level=level,
        winners=winners,
        advisor=advisor,
    )
    award.certificates.set(_store_images(certificates, uploader=uploader))
    award.photos.set(_store_images(photos, uploader=uploader))

    record_audit(
        action="content.award.create",
        user=uploader,
        target=award,
        detail={
            "year": year,
            "certificates": len(certificates),
            "photos": len(photos),
        },
        request=request,
    )
    logger.info(
        "content.award.create.success award_id=%s title=%s year=%s certificates=%s photos=%s user=%s",
        award.pk,
        title,
        year,
        len(certificates),
        len(photos),
        uploader.get_username(),
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return award


def _store_images(uploads, *, uploader):
    """把上传的图片收进共享媒体库，返回 MediaFile 列表。

    进的是公开媒体库（``/media/`` 由 Nginx 直出），与后台挂附件走的是同一处：
    获奖页面本来就对匿名访客开放，这些图没有额外的可见性要守。上传人记成提交者，
    出问题时查得到是谁传的。
    """
    return [
        MediaFile.objects.create(file=upload, kind=MediaFile.IMAGE, uploader=uploader)
        for upload in uploads
    ]
