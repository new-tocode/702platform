# 架构文档

按 Django app 分篇。**改哪块看哪篇**，不必从头读。

## 先看这两篇

| 文档 | 内容 |
|---|---|
| [overview.md](overview.md) | 平台是什么、给谁用、技术选型与理由、模块怎么划分 |
| [permissions.md](permissions.md) | 谁能做什么：角色表、权限矩阵、对象级权限、身份怎么管理 |

`permissions.md` 值得早看：这个项目里绝大多数「这个功能谁能用」的问题，答案都在那一篇，
而且判定函数都收敛在少数几个 `permissions.py` 里。

## 按 app 分的数据模型

| 文档 | 覆盖 |
|---|---|
| [accounts.md](accounts.md) | 账号、个人资料、头像与图册、强制改密、身份目录 |
| [projects.md](projects.md) | 项目组、联系人、指导老师、入组申请、申请建组 |
| [reviews.md](reviews.md) | 项目书同行评审（**最复杂的一篇**：送审、初审关卡、抽人、归档、请假、改派、超级评审） |
| [notices.md](notices.md) | 公告的三种可见范围 |
| [content.md](content.md) | 公开页与媒体库 |
| [competitions.md](competitions.md) | 竞赛与报名 |
| [equipment.md](equipment.md) | 设备台账与借用 |
| [discussion.md](discussion.md) | 社团空间：板块、帖子、评论、成员目录 |
| [core.md](core.md) | 操作入口注册表、审计日志、通用上传校验 |

## 横切与参考

| 文档 | 内容 |
|---|---|
| [security.md](security.md) | 安全设计要点（完整审查见 [安全检查.md](../../安全检查.md)） |
| [routes.md](routes.md) | 全部页面与地址 |
| [flows.md](flows.md) | 九条关键流程的端到端走法 |
| [roadmap.md](roadmap.md) | 已落地能力与可选扩展 |

## 每篇的写法

正文只讲三件事：**表结构**、**为什么这么设计**、**改动时不能破坏什么**。开头那句
引用块是给「偶然翻到这里」的人看的——一句话说清这篇覆盖什么、什么时候该看它。

`§N` 这种章节号引用已经全部换成文件链接：拆篇之后章节号会漂，链接不会。
