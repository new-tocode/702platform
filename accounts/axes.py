"""登录锁定的响应与审计。

django-axes 负责「数失败次数、判断是否锁着」，本模块只做两件它管不到的事：

* 把锁定时的响应换成站内一致的中文提示（它自带的那个是英文裸页，与本平台其他
  页面读起来对不上）；
* 把锁定写进 ``core.audit``——「谁在什么时候被锁了」是要能事后回看的，尤其在真的
  发生撞库时；审计日志本身在后台只读，写在这里比留在 axes 自己的表里更容易被
  管理员看到。

放在 accounts 下而不是 core 下，是因为它讲的就是账号与登录这件事。
"""

import logging

from django.conf import settings
from django.http import HttpResponse
from django.utils.translation import gettext as _


logger = logging.getLogger(__name__)

#: 锁定响应的状态码。用 403 而不是 429：这是「不许继续尝试」而不是「请求太频繁」，
#: 与站内其他权限拒绝保持同一口径。
LOCKOUT_STATUS = 403


def _cooloff_text():
    """把冷却时长说成人话；配置里是小时（可能是 0.5 这样的小数）。"""
    hours = settings.AXES_COOLOFF_TIME
    if not hours:
        return _("请稍后再试。")
    minutes = int(round(float(hours) * 60))
    if minutes and minutes % 60 == 0:
        return _("请 %(hours)s 小时后再试。") % {"hours": minutes // 60}
    return _("请 %(minutes)s 分钟后再试。") % {"minutes": minutes}


def lockout_response(request, original_response=None, credentials=None):
    """账号或 IP 被锁时返回的页面。

    axes 在**口令校验之前**调用它，所以正确的口令同样拿不到会话——「锁定」因此
    是一道真闸门，而不是一句提示。

    签名跟着 axes 的主调用约定走（``get_lockout_response`` 传三个位置参数）。
    异步路径下 axes 会退回两参数调用，那种情况下第二个参数其实是 credentials，
    所以下面按「哪个是字典」来判断，不靠位置硬猜。

    ``credentials`` 里的用户名只用于审计留痕（谁被锁了），口令本身从不记录——这条
    约定与 ``accounts.signals`` 里那条一致。
    """
    if credentials is None and isinstance(original_response, dict):
        credentials = original_response

    username = ""
    if isinstance(credentials, dict):
        username = credentials.get("username", "") or ""

    # 局部导入：accounts.axes 在 settings 加载期就可能被 import_string 解析，
    # 那时模型层未必已经就绪。
    from core.audit import record_audit

    record_audit(
        action="accounts.login.lockout",
        detail={"username": username, "path": getattr(request, "path", "")},
        request=request,
    )
    logger.warning(
        "auth.login.lockout username=%s path=%s remote=%s",
        username or "-",
        getattr(request, "path", "-"),
        request.META.get("REMOTE_ADDR", "-"),
        extra={"request_id": getattr(request, "request_id", "-")},
    )

    message = _("登录尝试次数过多，该账号或该网络已被暂时锁定，%(cooloff)s") % {
        "cooloff": _cooloff_text()
    }
    # 标题先在 f-string 外取好：xgettext 扫不到 f-string 内部的 _()，
    # 写在里面这条文案就不会进 .po，英文界面上它会原样露出中文。
    title = _("登录已锁定")
    html = (
        '<!doctype html><html lang="zh-hans"><head><meta charset="utf-8">'
        f"<title>{title}</title></head>"
        f"<body><p>{message}</p></body></html>"
    )
    return HttpResponse(
        html, status=LOCKOUT_STATUS, content_type="text/html; charset=utf-8"
    )
