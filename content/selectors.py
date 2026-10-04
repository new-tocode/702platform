"""只读查询：公开的获奖清单。不写库，也不做权限判定。"""

from django.db.models import Q

from .models import Award
from .tier_rules import NATIONAL, PROVINCIAL, SCHOOL


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

    condition = Q()
    for field in SEARCH_FIELDS:
        condition |= Q(**{f"{field}__icontains": keyword})
    condition |= Q(year__icontains=keyword)
    tier = TIER_KEYWORDS.get(keyword)
    if tier:
        condition |= Q(tier=tier)
    return awards.filter(condition)
