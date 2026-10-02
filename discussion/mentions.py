"""帖子与评论里的 @ 提及：从文本里解析出被提到的人。

服务端是权威：正文里写了 ``@姓名`` 就算提及，前端的补全只是帮忙打字——没脚本
时手打一样生效。当前只认人名（``Profile.full_name``），账号名不算；同名的姓名
会把提到的那一份发给所有同名账号（演示库当前没有重名，真出现时这条规则仍然
说得通：发帖人写的就是那个名字）。

消息的写入与撤回不在这里——那是 ``notices.services.sync_mention_messages`` 的
事，本模块只回答「这段文本提了谁」。
"""

import re

from django.contrib.auth import get_user_model


User = get_user_model()


def name_map():
    """``{姓名: [用户, ...]}``：有姓名的活跃账号。

    首改密中的账号也在内——他们改完密码就能看帖，@ 他们的消息放着不碍事。
    """
    mapping = {}
    users = (
        User.objects.filter(is_active=True)
        .exclude(profile__full_name="")
        .select_related("profile")
    )
    for user in users:
        name = user.profile.full_name.strip()
        if name:
            mapping.setdefault(name, []).append(user)
    return mapping


def mentionable_names():
    """补全列表用的姓名：去重、按名字排序。"""
    return sorted(name_map())


def extract_mentions(text):
    """文本里提到的人，按出现顺序去重。

    以姓名集合做**最长匹配**：姓名按长度降序拼成正则的 alternation，``@张三丰``
    不会被拆成 ``@张三`` 再搭一个字（``re`` 的交替是最左优先，所以长的必须排在
    前面）。``@`` 前不能是字母数字，邮箱里的 @ 不算提及。
    """
    if not text:
        return []
    names = name_map()
    if not names:
        return []
    pattern = re.compile(
        r"(?<![0-9A-Za-z_])@("
        + "|".join(
            re.escape(name) for name in sorted(names, key=len, reverse=True)
        )
        + r")"
    )
    mentioned, seen = [], set()
    for match in pattern.finditer(text):
        for user in names[match.group(1)]:
            if user.pk not in seen:
                seen.add(user.pk)
                mentioned.append(user)
    return mentioned
