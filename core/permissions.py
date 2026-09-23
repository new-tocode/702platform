"""跨应用的通用权限口径。

「谁算管理员」过去散在十几处，还分裂成两种写法（``is_staff`` 与
``is_staff or is_superuser``）。同一个问题有两个答案迟早会分叉，所以收敛到这里：
其余模块一律问 :func:`is_admin`。

视图门槛的样板也收在这里。八个 ``_require_*`` 函数逐字同构——记一条结构化警告、
再抛 ``PermissionDenied``——只有判据与日志文案不同；:func:`require` 留下这两样，
把样板吃掉。判据本身仍由各应用的 ``permissions`` 模块提供，这里不重复任何业务口径。
"""

import logging

from django.core.exceptions import PermissionDenied


logger = logging.getLogger(__name__)


def is_admin(user):
    """平台管理员：``is_staff`` 或 ``is_superuser``。

    Django 的 ``create_superuser`` 保证超级用户同时是 staff，两者实际不会分叉；
    把两种写法统一到这里，「谁算管理员」才只有一个答案。
    """
    return bool(
        user and user.is_authenticated and (user.is_staff or user.is_superuser)
    )


def require(request, predicate, event, **fields):
    """视图门槛：``predicate`` 不成立就记一条警告并抛 ``PermissionDenied``。

    ``event`` 是日志前缀（如 ``"reviews.permission.denied"``），``fields`` 是
    附带的定位信息，按 ``key=value`` 追加在用户名之后。格式与各入口原先逐字一致，
    只是 ``reason`` 这类字段现在统一排在 ``path`` 之前。
    """
    if predicate:
        return
    detail = "".join(f" {key}={value}" for key, value in fields.items())
    logger.warning(
        "%s username=%s%s path=%s",
        event,
        request.user.get_username(),
        detail,
        request.path,
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    raise PermissionDenied
