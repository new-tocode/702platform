"""别处的页面要用「我的消息」这一块时，由本模块挑好上下文。

与 :mod:`reviews.panels` 同一个模式：页面（accounts 的 ``member_home``、只读资料页）
只负责摆，「我这一块显示什么」由各应用自己挑好。未读计数走 :mod:`notices.selectors`
的唯一口径，没有未读时是 0，模板据此不渲染提醒。
"""

from .forms import DirectMessageForm
from .selectors import unread_message_count


def member_home_context(*, user):
    """「我的消息」的未读计数，供成员中心的提醒条与入口徽标取用。"""
    return {"unread_messages": unread_message_count(user)}


def direct_compose_context():
    """「写私信」小浮动窗要的那只空表单（见 ``templates/includes/direct_compose.html``）。

    别的应用在自己的页面上挂这个窗口时把它并进上下文即可——窗口的字段、标签与字数上限
    只有 notices 一处拥有，那个页面不用认识私信长什么样。
    """
    return {"direct_form": DirectMessageForm()}
