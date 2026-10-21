"""社团成果的写操作：事务边界、审计、领域异常都在这里。

获奖与论文都有判重，写入要在同一个事务里拿咨询锁、再查一次；专利的重复由数据库
唯一约束兜底，视图里一行保存 + 一条审计即可。视图只负责取表单、调这里、把结果
翻译成页面上的话。
"""

import logging

from django.db import connection, transaction

from core.audit import record_audit
from media.models import MediaFile

from .models import AcademicPaper, Award
from .selectors import find_duplicate_paper
from .similarity import find_similar_award, identity_key
from .tier_rules import normalize


logger = logging.getLogger(__name__)


class DuplicateAward(Exception):
    """已经有一条同样的获奖记录。带着那一条，好让页面把它指出来。"""

    def __init__(self, existing):
        super().__init__(f"duplicate of award #{existing.pk}")
        self.existing = existing


class DuplicatePaper(Exception):
    """已经有一篇题目、作者、年份都相同的论文。"""

    def __init__(self, existing):
        super().__init__(f"duplicate of paper #{existing.pk}")
        self.existing = existing


def _paper_identity_key(*, title, authors, year):
    """论文判重的身份串，同时是咨询锁的键。

    与 ``Award`` 的身份串同一条规矩：锁的对象必须与查的对象是同一个串。归一化只
    用 ``tier_rules.normalize``（全半角、大小写、空白与标点），不引入相似度。
    """
    return f"{year}\x1f{normalize(title)}\x1f{normalize(authors)}"


@transaction.atomic
def create_paper(
    *,
    title,
    authors,
    venue,
    year,
    paper_type,
    indexing="",
    doi="",
    abstract="",
    user,
    request=None,
):
    """新建一篇论文；同一身份（年 + 题目 + 作者）只允许一条。

    表单已经查过一次，那是为了在页面上立刻给出提示；这里在咨询锁里再查一次，
    挡的是两个请求都在对方写入前查完、然后各自保存的并发重复。论文没有数据库
    唯一约束（题目与作者是文本，归一化键不落库），咨询锁是唯一的并发防线。
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            [_paper_identity_key(title=title, authors=authors, year=year)],
        )

    existing = find_duplicate_paper(title=title, authors=authors, year=year)
    if existing is not None:
        logger.info(
            "content.paper.create.duplicate title=%s year=%s existing_id=%s user=%s",
            title,
            year,
            existing.pk,
            user.get_username(),
            extra={"request_id": getattr(request, "request_id", "-")},
        )
        raise DuplicatePaper(existing)

    paper = AcademicPaper.objects.create(
        title=title,
        authors=authors,
        venue=venue,
        year=year,
        paper_type=paper_type,
        indexing=indexing,
        doi=doi,
        abstract=abstract,
    )
    record_audit(
        action="content.paper.create",
        user=user,
        target=paper,
        detail={"year": year},
        request=request,
    )
    logger.info(
        "content.paper.create.success paper_id=%s title=%s year=%s user=%s",
        paper.pk,
        title,
        year,
        user.get_username(),
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return paper


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
    **这条记录的身份**（年份、层级与两个字段归一化之后的串），事务结束自动释放。
    哈希撞车只会让两个不相干的记录排队，不影响正确性。
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            [
                identity_key(
                    competition=competition,
                    tier=tier,
                    year=year,
                    winners=winners,
                )
            ],
        )

    existing = find_similar_award(
        competition=competition, tier=tier, year=year, winners=winners
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
