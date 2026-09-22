"""平台上全部身份的目录。

身份有两种来源，管理方式因此必须不同：

* ``GLOBAL``——管理员**授予**的资格（管理员、评审人、初审人、超级评审）：
  与任何对象无关，所以可以批量授予、批量撤销；
* ``OBJECT``——业务动作**产生**的事实（项目组联系人、项目组成员）：必须依附
  一个具体的项目组（入组申请通过、建组申请通过、联系人转让），所以后台只给
  名册，不提供任何直接分配的入口。让管理员随手把某人设成某组联系人、却没有
  对应的那条业务记录，身份就与项目组脱节了。

这里只登记「有哪些身份、各自叫什么、从哪来」，供后台的「身份管理」分组与
名册页取用。判定仍在各应用的 ``permissions``（谁有什么身份），授予仍在各应用
的 ``services``（怎么给出去）——目录不重复这两件事。

文案一律写中文原样、不进翻译：它只出现在 ``/admin/``，而后台不在双语范围内，
与模型的 ``verbose_name`` 一致。
"""

from dataclasses import dataclass
from enum import StrEnum
import logging
from threading import RLock


logger = logging.getLogger(__name__)


class Scope(StrEnum):
    """身份依附于什么。"""

    GLOBAL = "global"  # 挂在账号上，与任何对象无关
    OBJECT = "object"  # 相对于某个项目组成立


@dataclass(frozen=True)
class Role:
    key: str
    label: str
    summary: str
    scope: Scope
    sort_order: int = 100


_ROLES = {}
_LOCK = RLock()


def register_role(*, key, label, summary, scope, sort_order=100):
    """登记一种身份。

    按 ``key`` 幂等，与操作入口注册表同一套写法：``AppConfig.ready()`` 在开发
    自动重载时会跑多次，重复登记只是覆盖旧定义，不会长出第二份。
    """
    role = Role(key=key, label=label, summary=summary, scope=scope, sort_order=sort_order)
    with _LOCK:
        previous = _ROLES.get(key)
        _ROLES[key] = role
    logger.debug(
        "role_registry.register key=%s scope=%s replaced=%s",
        key,
        scope,
        previous is not None,
    )
    return role


def get_roles():
    """全部身份，按 ``sort_order`` 排序——后台分组的顺序由此固定。"""
    with _LOCK:
        return tuple(sorted(_ROLES.values(), key=lambda role: (role.sort_order, role.key)))


def get_role(key):
    """按 key 取一种身份；没有登记时返回 ``None``。"""
    with _LOCK:
        return _ROLES.get(key)
