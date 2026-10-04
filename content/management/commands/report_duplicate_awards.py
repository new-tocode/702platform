"""列出疑似重复的获奖记录：只读，不改数据。

判重现在拦得住新提交，但**已经录进去的成对记录不会自己消失**——「省一等奖」与
「东北赛区一等奖」当时就是两条都放行了。这条命令把它们列出来，由管理员在后台挑一条
留下、其余删掉：合并要人判断（留哪条证书、哪段描述），命令不替人做这个决定。

分组口径：同一年份、同一层级，赛事与获奖人在归一化、折叠、**并把层级记号去掉**之后
完全相同——「全国大学生物联网设计竞赛」与「…竞赛东北赛区」是同一场比赛的两种写法，
所以落在同一组。比判重更严一点：错别字那一档（靠相似度拦下的）不报。宁可少报——
报出来的都能直接动手，误报只会让人白跑一趟。
"""

from django.core.management.base import BaseCommand

from content.models import Award
from content.tier_rules import drop_tier_terms, normalize


#: 层级没填的历史记录，分组时也得有个说法。
_UNKNOWN_TIER = "（层级未填）"


class Command(BaseCommand):
    help = "列出疑似重复的获奖记录（同年份、同层级、同赛事、同批人）；只读，不修改数据"

    def handle(self, *args, **options):
        groups = {}
        for award in Award.objects.all().order_by("-year", "-created_at", "-id"):
            key = (
                award.year,
                award.tier,
                drop_tier_terms(normalize(award.competition)),
                drop_tier_terms(normalize(award.winners)),
            )
            groups.setdefault(key, []).append(award)

        duplicates = [rows for rows in groups.values() if len(rows) > 1]
        if not duplicates:
            self.stdout.write("没有发现疑似重复的获奖记录。")
            return

        # 新的在前：刚录进去的那条多半是多余的那条。
        for rows in sorted(duplicates, key=lambda rows: (rows[0].year, rows[0].pk), reverse=True):
            head = rows[0]
            self.stdout.write(
                f"—— {head.year} · {head.get_tier_display() or _UNKNOWN_TIER} ——"
            )
            for award in rows:
                self.stdout.write(
                    f"  #{award.pk} {award.title}｜{award.competition}｜"
                    f"{award.winners}｜{award.level}｜建 {award.created_at:%Y-%m-%d}"
                )
            self.stdout.write("")

        total = sum(len(rows) for rows in duplicates)
        self.stdout.write(
            self.style.WARNING(
                f"共 {total} 条记录落在 {len(duplicates)} 组疑似重复里；"
                "请在后台逐组确认，留下一条、删除其余。"
            )
        )
