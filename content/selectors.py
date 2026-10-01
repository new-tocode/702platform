"""只读查询：公开的获奖清单。不写库，也不做权限判定。"""

from django.db.models import Q

from .models import Award


#: 搜索框扫过的文本字段。年份是整数列，单独处理。
SEARCH_FIELDS = ("title", "competition", "level", "winners", "advisor")


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
    return awards.filter(condition)
