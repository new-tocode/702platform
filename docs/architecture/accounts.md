# accounts

> 账号、个人资料与身份。**模块说明（职责、接口、不变量、失败模式、测试与限制）在
> [`accounts/README.md`](../../accounts/README.md)**——表结构、规则与坑都搬去了那里，
> 因为它跟代码放在一起才不会被改漏。
>
> 这一篇只留**跨模块口径与由来**：账号这块与别处怎么耦合、某些设计当初为什么这么定。

**什么时候看**：改一处判定却不确定该问谁、或想知道某个历史包袱的来历。

---

## 跨模块口径

- **三种「组」不是一回事**，混起来是最常见的误读：Django `auth.Group` 是**内部通知的投递范围**（`Notice.visible_groups`）；`ProjectGroup` 是项目组本身；身份名册（`AdminRole` 等四个 proxy）只是 `User` 上布尔字段的一个视图，不建表。**用户组不是身份**，不进 `core.roles` 目录。
- **身份按来源分两种作用域**：`GLOBAL`（管理员授予、后台可批量改）与 `OBJECT`（业务动作产生、名册只读不给分配入口）。后台「身份管理」分组的依据、「为什么对象身份没有分配入口」见 [permissions.md](permissions.md)。
- **「当前身份」清单是两处共用的**：个人信息页与成员只读资料页都走 `accounts.selectors.member_identities`——全局身份问各 app 的 `permissions`，项目组那两项来自 `projects.selectors`。改身份显示口径会同时动到这两张页面。
- **头像与图册的取件口在 accounts**（`accounts:avatar_file` / `accounts:gallery_file`），但上传校验、存储、指纹、取件响应分别归 `core.uploads` / `core.storage` / `core.hashing` / `core.downloads`——这四个 core 模块的口径一变，这里要跟着验。

## 由来

- **`first_name` / `last_name` 为什么还在表上**：`User` 继承 `AbstractUser` 带来的历史列，界面与业务都改用 `Profile.full_name`，历史数据由迁移 `0004_copy_legacy_names` 合并过去。留着是因为删列要动 `AbstractUser` 的既有契约，收益不抵风险——但**别再把它接回业务**。
- **为什么没有 `accounts/permissions.py`**：这个 app 不产出任何「谁能做什么」的判定——管理员问 `core.permissions`，联系人／成员问 `projects.permissions`，评审资格问 `reviews.permissions`。在这里新写一条判定，就是开出第二处真相。
- **强制改密的拦截为什么在中间件**：标志字段在 accounts，但拦截必须是全局的（含 `/admin/`），所以放在 `config.middleware.ForcePasswordChangeMiddleware`。
- **登录锁定为什么不是自己写的**：计数、冷却、锁定判定都归 django-axes 与 `config/settings.py` 的 `AXES_*`；`accounts.axes` 只把锁定响应换成站内中文页并写审计。
