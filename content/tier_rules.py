"""获奖文本的归一化，以及层级措辞的折叠与推断（纯文本，不依赖 Django）。

层级在证书上有许多种写法：「省一等奖」「东北赛区一等奖」「黑龙江赛区一等奖」……
它们是同一层（省级），字面上却几乎没有共同的三元组——pg_trgm 在短串上实测只有
0.18，远在判重阈值 0.55 之下，于是同一条奖被重复录入。这里把这层意思从文字里提出来，
供两处使用：

* :func:`fold_tier_terms` —— 判重比较前的折叠。「省一等奖」与「东北赛区一等奖」折完
  是同一个串，判重的第一关（归一化后完全相同）就拦得住，不必指望相似度。
* :func:`derive_tier` —— 从自由文本里推断层级，给数据迁移回填历史记录用。
* :func:`drop_tier_terms` —— 折叠之后再把层级记号去掉，给重复清单分组用：赛事名里
  写没写赛区，不该影响「这是不是同一场比赛」的判断。

单独成模块、且不 import 模型，是为了让数据迁移能直接引它：迁移跑在模型的历史状态上，
引运行期的应用代码是给自己埋雷；这里只有字符串规则，没有那层顾虑。

**折叠不是判重的判据。** 判重比的是记录上存下来的 ``Award.tier``（新记录由填写者选定、
历史记录由迁移回填）；折叠只负责把「同一层级的两种写法」对齐，以及在回填时把老记录的
层级认出来。折叠记号直接用存储码（``provincial`` 这些）——它就是页面上「省级」那个值的
本名，只是从不显示给人看。
"""

import re
import unicodedata


#: 层级的存储码（``Award.tier`` 的值），同时也是折叠记号。两者必须是同一套：否则
#: 「折出来相等」与「存下来相等」会变成两件事。
NATIONAL = "national"
PROVINCIAL = "provincial"
SCHOOL = "school"


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


#: 大区与省级行政区。写成枚举而不是「几个字 + 赛区」的通配，是为了只吃掉地名本身：
#: 「全国大学生物联网设计竞赛东北赛区」里的「竞赛」不能被卷进来——卷进来，两种写法
#: 就折不成同一个串了。
_REGIONS = (
    "东北|华北|华东|华中|华南|西南|西北|港澳台|"
    "黑龙江|吉林|辽宁|北京|天津|河北|山西|内蒙古|"
    "上海|江苏|浙江|安徽|福建|江西|山东|河南|湖北|湖南|"
    "广东|广西|海南|重庆|四川|贵州|云南|西藏|"
    "陕西|甘肃|青海|宁夏|新疆|香港|澳门|台湾"
)

#: 「X赛区」→ 省级。地名缺省（光一个「赛区」）也算：赛区就是省级那一轮。
_AREA = re.compile(rf"(?:{_REGIONS})?赛区")

#: 名次词前光秃秃的一个「省」——「省一等奖」。只有紧挨着名次词时才当层级词，
#: 否则「黑龙江省大学生程序设计竞赛」这类赛事名会被误折。
_LONE_PROVINCE = re.compile(r"省(?=(?:特等|一等|二等|三等|金|银|铜)奖)")

#: 其余的层级词 → 记号。长词在前，免得「国家级」被「国家」先吃掉半截。
_ALIASES = (
    (re.compile(r"国家级|国赛|国家|全国"), NATIONAL),
    (re.compile(r"省级|省赛|区域赛|分区赛"), PROVINCIAL),
    (re.compile(r"校级|校赛"), SCHOOL),
)

#: 名次词。「优秀奖」「入围奖」这类不在此列，推断会落到整串扫描上。
_RANK = re.compile(r"特等|一等|二等|三等|金|银|铜")

#: 推断时在名次词前面回看的字数：够看到「东北赛区」「国家级」这样的限定词。
_LOOKBEHIND = 8


def fold_tier_terms(text):
    """把层级写法折成统一记号。输入应当是 :func:`normalize` 过的串。"""
    if not text:
        return ""
    folded = _AREA.sub(PROVINCIAL, text)
    folded = _LONE_PROVINCE.sub(PROVINCIAL, folded)
    for pattern, mark in _ALIASES:
        folded = pattern.sub(mark, folded)
    return folded


def drop_tier_terms(text):
    """折叠之后把层级记号也去掉，剩下的就是「说的是哪场比赛、哪批人」。

    给重复清单分组用：「全国大学生物联网设计竞赛」与「…竞赛东北赛区」是同一场比赛的
    两种写法，一个写了赛区、一个没写——判重那边靠相似度兜住（0.67），清单这边要的
    是一个能把它们放进同一组的键。去掉记号比留着记号更接近这个意思。
    """
    folded = fold_tier_terms(text)
    for mark in (NATIONAL, PROVINCIAL, SCHOOL):
        folded = folded.replace(mark, "")
    return folded


def derive_tier(*texts):
    """从若干段自由文本里推断层级，按顺序取第一个认得出的；认不出返回空串。

    优先看名次词前面那一小段：说明层级的是紧挨「一等奖」的那个词，而开头的「全国」是
    赛事名的一部分——「全国大学生物联网设计竞赛东北赛区一等奖」说的是省级，不是国家级。
    名次词附近没有层级词时，再退回到整串扫描（「国家级」这类记录就不带名次词）。
    """
    for text in texts:
        normalized = normalize(text)
        if normalized:
            tier = _tier_before_rank(normalized) or _tier_in(normalized)
            if tier:
                return tier
    return ""


def _tier_before_rank(normalized):
    """名次词前一小段里的层级词。"""
    match = _RANK.search(normalized)
    if not match:
        return ""
    window = normalized[max(0, match.start() - _LOOKBEHIND) : match.start()]
    return _tier_in(window) if window else ""


def _tier_in(text):
    """一段文字里有没有层级词。同时出现时按「学校 → 省 → 国」取更具体的那一个。"""
    folded = fold_tier_terms(text)
    for mark in (SCHOOL, PROVINCIAL, NATIONAL):
        if mark in folded:
            return mark
    return ""
