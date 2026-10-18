"""别处的页面要用「我的消息」这一块时，由本模块挑好上下文。

与 :mod:`reviews.panels` 同一个模式：页面（accounts 的只读资料页）只负责摆，
「我这一块显示什么」由各应用自己挑好。

**未读计数不在这里**：顶栏徽标长在每一页上，所以那个数由
:mod:`notices.context_processors` 作基底上下文处理器统一给——成员中心那一页的
提醒条与入口徽标取的也是它。页面再装配一遍，就是同一个数在一个请求里算两遍。
"""

from .forms import DirectMessageForm


def direct_compose_context():
    """「写私信」小浮动窗要的那只空表单（见 ``templates/includes/direct_compose.html``）。

    别的应用在自己的页面上挂这个窗口时把它并进上下文即可——窗口的字段、标签与字数上限
    只有 notices 一处拥有，那个页面不用认识私信长什么样。
    """
    return {"direct_form": DirectMessageForm()}
