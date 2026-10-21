"""「谁能往前台的社团成果里添东西」的口径。

只有一条：登录成员。判据不在这里另写一遍，直接问 ``discussion.permissions.is_member``
（登录、账号启用、且已完成首次改密）——同一个问题有两个答案，迟早会分叉。公开页面
的读取不需要任何身份，所以这里管的是下载与添加这两个动作。

函数名沿用「获奖」时代的 ``can_manage_awards``：它现在也管论文与专利的添加。改名会扩散
到所有调用点与测试，而函数体只有一条 ``is_member``，不值得为名字单独做一次重构。
"""

from discussion.permissions import is_member


def can_manage_awards(user):
    """能否打包下载证书，以及能否添加获奖／论文／专利记录。"""
    return is_member(user)
