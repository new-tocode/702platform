"""获奖记录的判重：同一年、同一赛事、同一批获奖人、同一层级，就是同一条。

不同获奖人各自记录同一场比赛的同一个奖，是两条记录——「我的获奖」按姓名搜索时
每个人都要查得到自己那条，所以判重**不能**只看赛事与年份。

判重的身份是**结构化的**：年份 + 赛事 + 获奖人 + 层级。层级是 ``Award.tier`` 这个
枚举，不是证书上的写法——「省一等奖」与「东北赛区一等奖」是同一层，措辞的差别不该
让它们变成两条（这正是过去漏判的那一类）。奖项名称与级别写法因此不参与判重：它们是
这条记录的说明，不是它的身份。

由此定下一条口径：**同一层级下，同一年、同一赛事、同一批人只允许一条**。往年那种
「数学建模一等奖」与「数学建模二等奖」各录一条的情况，现在算重复——一个队在同一年
的同一场比赛里只会拿到一个名次；确实是另一条的（换个赛道之类），走后台那条放行的路
（见 docs/architecture/content.md）。

比较因此是**逐字段**的，而不是给整串打一个总分：整串相似度会被长字段稀释——赛事名
几十个字、获奖人几个字，合在一起算，短字段上换个名字也未必跌到阈值以下。逐字段
之后，每个字段跟自己的门槛比，短字段上的差别不会被长字段盖过去。

**算法是 PostgreSQL 的 pg_trgm**，逐字段算三元组相似度。选它有三个理由：库里就
有（不必引依赖、不必自己实现）；中文按字切三元组，不需要分词；短串上的表现接近
「要么全同、要么全不同」，正合这里的需要。

**快在哪儿**：年份是硬判据——年份不等就不是同一条——所以先用年份筛一刀。这一步走
``Award.Meta.indexes`` 里已有的 ``(-year, -created_at)`` 索引，而且**永远不会漏掉
真正的重复**。剩下的候选只有那一年的几条到几十条，再逐条算相似度。没有为相似度建
GIN 索引：那种索引只在「拿相似度当检索条件」时才有用，而这里年份已经把候选收到
很小了，多一列指纹、多一次回填，换不来什么。

两道关，先便宜后贵：

1. **归一化后完全相同** —— NFKC 全角转半角、大小写压平、去掉空白与标点，再把层级
   措辞折成统一记号（见 ``content.tier_rules``）。空格、全半角、中英文标点这些差别
   不算差别；「省一等奖」与「东北赛区一等奖」折完也是同一个串。多数重复（同一个人
   把同一条又填了一遍）在这一关就拦下了，连相似度都不必算。
2. **逐字段相似度** —— 归一化之后仍可能差一个字（错别字、简写），交给 pg_trgm。

第二关里有一条容易写反的规矩：**任何一侧没填，这一项就不比**。「没填」不等于
「不一样」。新记录空着时按「不一样」处理，先加的那条填了获奖人、重复提交时留空就
绕过去了；老记录空着时按「不一样」处理，改必填之前录进来的那几条就永远拦不住重复。
层级同理：回填时认不出层级的老记录留的是空值，它不否决谁（「不确定」不该变成一次
莫名的拒绝），但也不该被当成「另一个层级」。

阈值是按实测定的，见 :data:`FIELD_THRESHOLDS`。
"""

import logging

from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import F, Q, Value

from .models import Award
from .tier_rules import fold_tier_terms, normalize


logger = logging.getLogger(__name__)


#: 逐字段的相似度门槛。实测：一字之差（建模竞赛 / 建模大赛）约 0.6，
#: 「张三、李四 / 张三、王五」这类换人约 0.5。0.55 落在「该拦的（≥0.6）」与
#: 「不该拦的（≤0.5）」中间，两边都留着余量。
FIELD_THRESHOLDS = {
    "competition": 0.55,
    "winners": 0.55,
}

#: 参与判重的字段。年份不在其中：它是硬判据，只做筛选，不比相似度。层级也不在：
#: 它比的是相等，不是相似。
_COMPARED_FIELDS = tuple(FIELD_THRESHOLDS)


def field_shape(**fields):
    """一条记录的「形状」：参与判重的字段各自归一化、折叠后拼起来，用来判完全相同。

    折叠见 :func:`tier_rules.fold_tier_terms`：它把层级措辞换成统一记号，证书上写
    「省一等奖」还是「东北赛区一等奖」都落到同一个串——两份记录整串写进同一个字段
    时，靠的就是这一关。
    """
    return "\x1f".join(
        fold_tier_terms(normalize(fields[name])) for name in _COMPARED_FIELDS
    )


def identity_key(*, competition, tier, year, winners):
    """判重用的身份串：年份 + 层级 + 两个字段的形状。

    判重拿它比，写入时也拿它加锁（见 ``content.services.create_award``）——两处
    必须是同一个串，否则锁住的不是正在比的那个东西。
    """
    return (
        f"{year}\x1f{tier}\x1f"
        + field_shape(competition=competition, winners=winners)
    )


def find_similar_award(*, competition, year, winners, tier, exclude_pk=None):
    """在同一年份、同一层级的记录里找与新记录重复的那一条，没有就返回 ``None``。

    ``exclude_pk`` 给编辑场景留的：改自己那条时，不该被自己挡住。
    """
    if not year:
        # 没有年份就没有可筛的范围，也就没有「同一条」可言。表单本来也要求填年份。
        return None

    values = {"competition": competition, "winners": winners}
    same_year = Award.objects.filter(year=year).order_by("-created_at", "-id")
    if exclude_pk:
        same_year = same_year.exclude(pk=exclude_pk)
    if tier:
        # 层级是身份的一部分：两边都知道、且不一样，就不是同一条。空值不否决——
        # 「没填」不等于「不一样」，与其余字段同一条规矩（回填时认不出层级的
        # 老记录留的就是空值）。
        same_year = same_year.filter(Q(tier="") | Q(tier=tier))

    # 第一关：归一化、折叠后一模一样。逐条比字符串，代价只有一次查询。
    wanted = field_shape(**values)
    for other in same_year:
        if field_shape(competition=other.competition, winners=other.winners) == wanted:
            return other

    # 第二关：逐字段相似度，交给 pg_trgm。**任何一侧没填，这一项就不比**——「没填」
    # 不等于「不一样」，当成不一样就等于给重复开一扇门（先加的那条填了获奖人、重复
    # 提交时留空，就绕过去了）。两边都要照顾：新记录空着是一种，老记录空着是另一种，
    # 拿它跟新记录一比就永远不相等。空串与空串的相似度是 0，所以这里不是「比出来
    # 相等」，是压根不比。
    conditions = Q()
    scores = {}
    for field in _COMPARED_FIELDS:
        value = (values[field] or "").strip()
        if not value:
            continue
        scores[f"{field}_score"] = TrigramSimilarity(F(field), Value(value))
        conditions &= Q(**{f"{field}__exact": ""}) | Q(
            **{f"{field}_score__gte": FIELD_THRESHOLDS[field]}
        )

    if not scores:
        # 两个字段都空着——第一关已经比过了，没有可以算相似度的东西。
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
