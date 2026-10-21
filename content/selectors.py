"""只读查询：公开的成果清单与聚合页统计。不写库，也不做权限判定。"""

from django.db.models import Count, Max, Q

from .models import (
    PAPER_INDEXING_CHOICES,
    PAPER_TYPE_CHOICES,
    PATENT_STATUS_CHOICES,
    PATENT_TYPE_CHOICES,
    AcademicPaper,
    Award,
    Patent,
)
from .tier_rules import NATIONAL, PROVINCIAL, SCHOOL, normalize


#: 搜索框扫过的文本字段。年份是整数列，单独处理。
SEARCH_FIELDS = ("title", "competition", "level", "winners", "advisor")

#: 整词命中这几个词时，连结构化层级一起找：页面上那条记录的 level 写的是「东北赛区
#: 一等奖」，字面上并不含「省级」，光靠 icontains 找不到它。只认整词——「全国大学生
#: 数学建模竞赛」里也含「全国」，按包含匹配就成了一次「所有国家级记录」的检索，
#: 那不是搜索的人想要的。
TIER_KEYWORDS = {
    "国家级": NATIONAL,
    "国赛": NATIONAL,
    "国家": NATIONAL,
    "省级": PROVINCIAL,
    "省赛": PROVINCIAL,
    "赛区": PROVINCIAL,
    "校级": SCHOOL,
    "校赛": SCHOOL,
}

#: 论文与专利的整词搜索：这些词的常见缩写不在 choices 的标签里，单列成别名。
#: 完整的标签（中文与英文）由 :func:`_choice_value` 从 choices 现取，两种界面
#: 各用各的语言，不在这里抄一份会在翻译后过期的英文。
PAPER_TYPE_ALIASES = {
    "期刊论文": "journal",
    "期刊": "journal",
    "会议论文": "conference",
    "会议": "conference",
}
PAPER_INDEXING_ALIASES = {
    "SCI": "sci",
    "EI": "sci",
    "SCI/EI": "sci",
    "SCI / EI": "sci",
    "中文核心": "core",
    "核心": "core",
    "其他收录": "other",
    "其他": "other",
    "未收录": "none",
}
PATENT_TYPE_ALIASES = {
    "发明专利": "invention",
    "实用新型": "utility",
    "外观设计": "design",
}
PATENT_STATUS_ALIASES = {
    "已授权": "granted",
    "授权": "granted",
    "审查中": "reviewing",
    "已申请": "applied",
    "申请中": "applied",
}


def _choice_value(choices, keyword, aliases):
    """把用户输入对到 choices 的存储码：存储码、当前语言标签、常见别名都认。

    标签从 choices 现取，所以中文界面输入「审查中」、英文界面输入 ``Under review``
    会落到同一个码值；否则英文 placeholder 承诺的「按状态搜」其实搜不到。
    """
    folded = (keyword or "").casefold()
    if not folded:
        return None
    # 别名的键写成「页面上的样子」（比如 ``SCI/EI``），这里统一按 casefold 比，
    # 否则用户输入小写时只有全大写的别名会漏掉。
    for alias, value in aliases.items():
        if alias.casefold() == folded:
            return value
    for value, label in choices:
        if not value:
            continue
        if folded == value.casefold() or folded == str(label).casefold():
            return value
    return None


def _search_condition(keyword, fields, year=True):
    """多个文本字段之间 OR 出一个关键字条件。"""
    condition = Q()
    for field in fields:
        condition |= Q(**{f"{field}__icontains": keyword})
    if year:
        condition |= Q(year__icontains=keyword)
    return condition


def search_awards(*, query=""):
    """按一个关键字过滤获奖记录，空关键字就是全部。

    只做一个搜索框、在多个字段之间 OR，而不是按字段分几个输入框：找一条记录的人
    心里想的是「张三那个建模奖」，不该先判断这句话属于哪个字段。icontains 在这个
    量级（几百条）够快；它用不上索引，但目前也只有它能让「24」命中 2024——
    年份要按数字前缀搜，就绕不开把整数列转成文本。
    """
    awards = Award.objects.prefetch_related("certificates", "photos")
    keyword = (query or "").strip()
    if not keyword:
        return awards

    condition = _search_condition(keyword, SEARCH_FIELDS)
    tier = TIER_KEYWORDS.get(keyword)
    if tier:
        condition |= Q(tier=tier)
    return awards.filter(condition)


def search_papers(*, query=""):
    """按一个关键字过滤论文，空关键字就是全部；规则与获奖搜索同一套。"""
    papers = AcademicPaper.objects.all()
    keyword = (query or "").strip()
    if not keyword:
        return papers

    condition = _search_condition(
        keyword, ("title", "authors", "venue", "doi", "abstract")
    )
    paper_type = _choice_value(PAPER_TYPE_CHOICES, keyword, PAPER_TYPE_ALIASES)
    if paper_type:
        condition |= Q(paper_type=paper_type)
    indexing = _choice_value(PAPER_INDEXING_CHOICES, keyword, PAPER_INDEXING_ALIASES)
    if indexing:
        condition |= Q(indexing=indexing)
    return papers.filter(condition)


def search_patents(*, query=""):
    """按一个关键字过滤专利，空关键字就是全部；规则与获奖搜索同一套。"""
    patents = Patent.objects.all()
    keyword = (query or "").strip()
    if not keyword:
        return patents

    condition = _search_condition(
        keyword, ("title", "inventors", "patent_number", "summary")
    )
    patent_type = _choice_value(PATENT_TYPE_CHOICES, keyword, PATENT_TYPE_ALIASES)
    if patent_type:
        condition |= Q(patent_type=patent_type)
    status = _choice_value(PATENT_STATUS_CHOICES, keyword, PATENT_STATUS_ALIASES)
    if status:
        condition |= Q(status=status)
    return patents.filter(condition)


def find_duplicate_paper(*, title, authors, year, exclude_pk=None):
    """同一年里，题目与作者归一化后都相同的论文；没有就返回 ``None``。

    只做「整串相同」，不学获奖的 pg_trgm 相似度：论文的错别字该由录入的人自己
    发现，而「同一篇又录了一遍」用归一化后的整串相同就能拦住。前台表单先用它
    给即时提示，写入服务在咨询锁里再查一次（并发双击的兜底）。
    """
    if year is None:
        return None
    wanted = (normalize(title), normalize(authors))
    papers = AcademicPaper.objects.filter(year=year).only("pk", "title", "authors")
    if exclude_pk:
        papers = papers.exclude(pk=exclude_pk)
    for paper in papers:
        if (normalize(paper.title), normalize(paper.authors)) == wanted:
            return paper
    return None


#: 聚合页上的三个栏目。键名同时是模板变量名，顺序即页面上的顺序。
ACHIEVEMENT_SECTIONS = (
    ("awards", Award),
    ("papers", AcademicPaper),
    ("patents", Patent),
)


def achievement_summary():
    """聚合页每张卡要的两个数：这一类有几条、最近是哪一年，外加总数。

    三类各一次聚合，不把三张表拼成一个大查询：模型之间没有关系，硬拼只会让
    模板拿到一堆需要再拆的列。总数只给视图日志用，页面不另设总览统计条。
    """
    summary = {}
    total = 0
    for key, model in ACHIEVEMENT_SECTIONS:
        stats = model.objects.aggregate(total=Count("pk"), latest=Max("year"))
        summary[key] = stats
        total += stats["total"]
    summary["total"] = total
    return summary
