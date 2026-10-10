# core

> 平台底座：跨应用权限口径、审计、上传校验、文件指纹、取件出口、操作入口注册表与身份目录。
> **模块说明（职责、接口、不变量、失败模式、测试与限制）在 [`core/README.md`](../../core/README.md)**。
>
> 这一篇只留**跨模块口径与由来**。

**什么时候看**：写审计、做视图门槛、碰文件的存储或指纹，或想确认某个「平台级口径」住在哪。

---

## 跨模块口径

- **审计 `action` 字符串是跨模块承诺**：一旦发布就不再改，历史记录要保持连续。新增写操作时照着相邻的那一个取名（清单见各 app 的 README）。
- **`get_client_ip` 是全站唯一的「来源 IP」口径**：审计记的 IP 与 django-axes 锁定的 IP 都取自它（`AXES_CLIENT_IP_CALLABLE` 指着同一个函数）。默认只信 `REMOTE_ADDR`，`TRUST_FORWARDED_FOR` 打开时才读 `X-Forwarded-For` 的**最后一段**——改它等于同时改「审计记了谁」与「谁被锁」，改错会让全站登录互相锁死，或让 IP 可被伪造。
- **指纹的三个约定**：`FileDigestMixin` 给带文件字段的模型算 SHA-256（七个字段都接了）；**项目书、批注版、归档版**的取件响应另带 `Content-Digest` 与 `X-Checksum-SHA256`（图片类刻意不发，见 [glossary.md](../glossary.md) 的「指纹」）；归档件与其来源任务的指纹相同——对不上就说明归档之后被动过。
- **存储的两类根是硬约定**：`PRIVATE_MEDIA_ROOT` 刻意不在 `MEDIA_ROOT` 之下，受保护件因此没有任何 HTTP 路径能直接命中。**这条边界是「取件必须走视图」的真正保障**——不是 `url()` 抛异常（它返回空串，理由见 `core/storage.py`）。
- **注册表与目录的登记约定**：各 app 在 `AppConfig.ready()` 里登记操作入口（`core/registry.py`）与身份（`core/roles.py`）；后台「身份管理」分组的顺序必须与 `core/roles` 的 `sort_order` 一致。判定仍归各 app 的 `permissions`，授予仍归 `services`——目录不重复这两件事。
- **边界**：`config/middleware.py`、`config/settings.py`、`config/admin.py` 归 **config 包**（见 [`config/README.md`](../../config/README.md)）；六个取件视图本身归各业务 app，用的才是 `core/downloads.serve_file`。

## 由来

- **指纹为什么存在模型自己身上**：文件会跟着记录一起死（换头像删旧图、删图册删盘、帖子图随编辑被替换），单开一张按文件名索引的旁表会在每条路径上留下没人清理的孤儿行。字段跟着行走，删记录即删指纹。
- **审计为什么只追加、又为什么由数据库来守**：它是「谁在什么时候动了什么」的底账，改动它等于篡改历史。最初只有后台类 `AuditLogAdmin` 在拦（禁增删改），脚本与 ORM 照样能改——「只追加」那时是约定。现在这条落到了数据库：迁移 `core.0003` 给 `core_auditlog` 挂了行级触发器，`UPDATE` / `DELETE` 一律 `RAISE EXCEPTION`。**为什么不做成「收权限」**：应用账号就是这张表的属主，属主的隐含权限 `REVOKE` 不掉，要收得先拆角色——那是部署形态的改动，比一条触发器贵得多（见 `core/README.md` 的不变量；逃生口见 [deploy.md](../deploy.md) §5.3）。
- **`core.storage.rehome` 当前没有调用点**：docstring 说「数据迁移与运维脚本共用它」，实际「受保护上传件搬家」那条迁移刻意另写了一份冻结实现（迁移不能依赖会变的代码）。留着它是给下一次搬家用的——**别按 docstring 以为它天天在跑**。
- **为什么 `url()` 返回空串而不是抛异常**：Django 的 `ClearableFileInput.is_initial()` 会主动求值 `.url`，抛出去会让模板渲染 500（实测 `{{ form.proposal }}` 直接 500）；`getattr(value, "url", False)` 带默认值也说明框架本就预期它可能取不到。护栏因此落在目录边界上。
