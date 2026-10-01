"""获奖记录的判重：同一奖项 + 同一批获奖人才算同一条。

不同获奖人各自记录同一场比赛的同一个奖，是两条记录——「我的获奖」按姓名搜索时
每个人都要查得到自己那条，所以判重**不能**只看赛事与年份。

比较因此是**逐字段**的，而不是给整串打一个总分。整串相似度会把「数学建模一等奖」
和「数学建模二等奖」判成同一条：三十个字的串里差一个字，分数仍在 0.9 以上，而这两
条恰恰必须分开。逐字段之后，「一等奖 / 二等奖」落在 title 这一个字段上，短串的三元
组本来就少，差异立刻显出来（实测 0.455）。

**算法是 PostgreSQL 的 pg_trgm**，逐字段算三元组相似度。选它有三个理由：库里就
有（不必引依赖、不必自己实现）；中文按字切三元组，不需要分词；短串上的表现接近
「要么全同、要么全不同」，正合这里的需要。

**快在哪儿**：年份是硬判据——年份不等就不是同一条——所以先用年份筛一刀。这一步走
``Award.Meta.indexes`` 里已有的 ``(-year, -created_at)`` 索引，而且**永远不会漏掉
真正的重复**。剩下的候选只有那一年的几条到几十条，再逐条算相似度。没有为相似度建
GIN 索引：那种索引只在「拿相似度当检索条件」时才有用，而这里年份已经把候选收到
很小了，多一列指纹、多一次回填，换不来什么。

两道关，先便宜后贵：

1. **归一化后完全相同** —— NFKC 全角转半角、大小写压平、去掉空白与标点。空格、
   全半角、中英文标点这些差别不算差别。多数重复（同一个人把同一条又填了一遍）
   在这一关就拦下了，连相似度都不必算。
2. **逐字段相似度** —— 归一化之后仍可能差一个字（错别字、简写），交给 pg_trgm。

阈值是按实测定的，见 :data:`FIELD_THRESHOLDS`。
"""

import logging
import unicodedata

from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import F, Q, Value

from .models import Award


logger = logging.getLogger(__name__)


#: 逐字段的相似度门槛。实测：一字之差（建模竞赛 / 建模大赛）约 0.6，
#: 「一等奖 / 二等奖」约 0.455，「张三、李四 / 张三、王五」这类换人约 0.5，
#: 「国家级 / 省级」为 0。0.55 落在「该拦的（≥0.6）」与「不该拦的（≤0.5）」
#: 中间，两边都留着余量。
FIELD_THRESHOLDS = {
    "competition": 0.55,
    "title": 0.55,
    "level": 0.55,
    "winners": 0.55,
}

#: 参与判重的字段。年份不在其中：它是硬判据，只做筛选，不比相似度。
_COMPARED_FIELDS = tuple(FIELD_THRESHOLDS)


def normalize(text):
    """把一段文字压成可比较的形状：全角转半角、大小写压平、去掉空白与标点。

    NFKC 管全角字母数字与常见标点的统称（``ＡＢ`` → ``AB``、``，`` → ``,``），
    但管不了中文异体字（``獎`` 仍是 ``獎``）——那类差别留给相似度那一关。
    """
    folded = unicodedata.normalize("NFKC", text or "").casefold()
    return "".join(
        char
        for char in folded
        if not char.isspace() and not unicodedata.category(char).startswith("P")
    )


def field_shape(**fields):
    """一条记录的「形状」：四个字段各自归一化后拼起来，用来判完全相同。"""
    return "\x1f".join(normalize(fields[name]) for name in _COMPARED_FIELDS)


def identity_key(*, competition, title, level, year, winners):
    """判重用的身份串：年份 + 四个字段的形状。

    判重拿它比，写入时也拿它加锁（见 ``content.services.create_award``）——两处
    必须是同一个串，否则锁住的不是正在比的那个东西。
    """
    return f"{year}\x1f" + field_shape(
        competition=competition, title=title, level=level, winners=winners
    )


def find_similar_award(*, competition, title, level, year, winners, exclude_pk=None):
    """在同一年份的记录里找与新记录重复的那一条，没有就返回 ``None``。

    ``exclude_pk`` 给编辑场景留的：改自己那条时，不该被自己挡住。
    """
    if not year:
        # 没有年份就没有可筛的范围，也就没有「同一条」可言。表单本来也要求填年份。
        return None

    values = {
        "competition": competition,
        "title": title,
        "level": level,
        "winners": winners,
    }
    same_year = Award.objects.filter(year=year).order_by("-created_at", "-id")
    if exclude_pk:
        same_year = same_year.exclude(pk=exclude_pk)

    # 第一关：归一化后一模一样。逐条比字符串，代价只有一次查询。
    wanted = field_shape(**values)
    for other in same_year:
        if field_shape(
            competition=other.competition,
            title=other.title,
            level=other.level,
            winners=other.winners,
        ) == wanted:
            return other

    # 第二关：逐字段相似度，交给 pg_trgm。空字段不比相似度（空串与空串的相似度是
    # 0，比不出「两边都没填」这件事），改成要求对方那个字段也是空的。
    conditions = Q()
    scores = {}
    for field in _COMPARED_FIELDS:
        value = (values[field] or "").strip()
        if not value:
            conditions &= Q(**{f"{field}__exact": ""})
            continue
        scores[f"{field}_score"] = TrigramSimilarity(F(field), Value(value))
        conditions &= Q(**{f"{field}_score__gte": FIELD_THRESHOLDS[field]})

    if not scores:
        # 四个字段全空：第一关已经比过了，没有可以算相似度的东西。
        return None

    return (
        same_year.annotate(**scores)
        .filter(conditions)
        .order_by(
            *[f"-{field}_score" for field in _COMPARED_FIELDS if f"{field}_score" in scores],
            "-created_at",
            "-id",
        )
        .first()
    )
