# core 模块

> 平台横向底座：跨应用权限口径（`is_admin` / 视图门槛 `require`）、审计日志、操作入口注册表、
> 身份目录、通用上传校验、文件指纹、受保护件的存储与取件出口，以及成员中心的概览计数。
> 它**只有一张表**（`AuditLog`），**没有页面**，也**不产出任何业务判定**——「谁能做什么」仍归
> 各 app 的 `permissions`，这里只统一口径与样板。

**什么时候看**：加一个成员入口、写审计、给视图加权限门槛、调上传校验或大小上限、
动文件存储与取件响应、加一种身份、改后台的只读名册，或改成员中心的概览数字时。

---

## 1. 明确不做什么

| 不在这里 | 落在哪 |
|---|---|
| 「谁能做什么」的业务判定 | 各 app 的 `permissions.py`。`core.permissions` 只有 `is_admin` 与门槛样板，**在这里新写一条业务判定就是开出第二处真相** |
| 入口的可见判据 | 注册表只按条件过滤与排序，`visible_when` 传进来的是各 app 自己的判定函数 |
| 身份怎么授予、存在哪 | 授予在 `accounts.services.set_qualification` 与后台批量动作；`roles.py` 只登记目录，不存第二处数据 |
| 请求 ID、强制改密、安全响应头、请求日志 | `config/middleware.py`（在 `config` 包，不在 core） |
| 公共装配：`INSTALLED_APPS`、context processor、`AXES_CLIENT_IP_CALLABLE`、两个媒体根 | `config/settings.py` |
| 后台首页的「身份管理」分组 | `config/admin.py`（它硬编码六张名册的清单，顺序要和 `core.roles` 的 `sort_order` 保持一致） |
| Nginx 直出的公开媒体库 | 公开件落 `MEDIA_ROOT`；`core.downloads` 只管受保护件的取件 |
| 六个取件视图本身 | `accounts.file_views` / `discussion.views` / `projects.views` / `reviews.views`；**权限判定在各自的视图里**，core 只负责把响应拼对 |
| 各入口的上限与文案（项目资料 500 MB、头像 2 MB……） | 各 app 的 `validators.py`；core 的 `validate_image_upload` 与 `validate_archive_upload` 都只收下 `label` 与 `max_bytes` |

## 2. 必须成立的断言

- **审计「只追加」是数据库在守，不是约定**：迁移 `core.0003` 的行级触发器
  `core_auditlog_append_only` 对 `core_auditlog` 的 `UPDATE` / `DELETE` 一律 `RAISE EXCEPTION`。
  脚本、`queryset.update()`、数据库客户端都改不动这张表里的**行**。**模型层没有写保护**
  （`AuditLog.save()` 照样发语句，只是数据库会拒）。行级而非语句级：`UPDATE … WHERE false`
  这类空语句放行。
- **删账号会被同一个触发器挡住**：`AuditLog.user` 是 `SET_NULL`，删用户前要先把他名下的审计行置空，
  而那是一次 `UPDATE`。所以**有审计行的账号删不掉**（一条都没有的照常删得掉）。这是刻意的：
  留痕不该因为删账号而变。平台因此把「停用」当作账号退场的口径。
- **`record_audit` 不体检 `detail`**：「只记非敏感信息」靠调用方自律，没有任何运行时过滤。
- **审计的事务边界由调用方决定**：core 不替调用方开事务——跟写操作同事务还是提交之后写，
  取决于调用点怎么安排（各 app 的做法见各自的 README）。
- **指纹跟着行走**（`sha256` 存在模型自己身上，不单开旁表）：文件会跟着记录一起死（换头像删旧图、
  删图册删盘、帖子图随编辑被替换），旁表会在这些路径上留下没人清理的孤儿行。
- **`FileDigestMixin.save(update_fields=[…])` 的两条规则**：带了文件列 → 算出的指纹**与现值不同**时
  会把它并进写入列表（换头像走的正是这条，不并进去就永远写不进去）；**没带**文件列 → 完全不动指纹
  （Django 不会落盘那个新文件，照内存里的内容重算就会与库里的文件对不上）。指纹没变就别硬塞。
- **算完必须把上传流拨回开头**，否则紧接着的落盘会存下一个空文件。
- **`digest_field` 只认一个文件字段**：平台上每个模型都只有一个；真有第二个时再把字段名变成参数。
  接了七个文件字段：项目资料、评审回复与归档件、头像与图册、帖子图、媒体库——**新增带文件字段的模型时
  照这个清单补**。
- **两个媒体根里的相对路径相同**：所以 `rehome` 搬完之后数据库字段一个字都不用改，迁移也因此天然幂等。
- **真正的屏障是目录边界，不是 `url()`**：`PrivateStorage.url()` 返回空串只是「别拼地址」的软约束；
  受保护件不在 `mediafiles/` 之下，Nginx 的 `/media/` 永远指不到它们。**把 `PRIVATE_MEDIA_ROOT`
  挪进 `MEDIA_ROOT`，全部取件判定立刻失效，而页面上看不出来。**
- **`upload_to` 是函数时 Django 原样采用返回值、不做 `strftime`**：日期目录要在函数里自己算。
  写 `upload_to="uploads/%Y/%m/"` 这种字符串才有 `strftime`，换成可调用对象时这一层就没了。
- **落盘名与用户填的名字彻底脱钩**：换成 uuid 并按年月分目录，只保留扩展名——原文件名会带人名、组名、
  项目名，而它会跟着文件走进备份、运维的 `ls` 与下载头。
- **注册表是进程内的内存态**，靠各 `AppConfig.ready()` 在启动时填充；按 `key` 幂等，
  所以开发自动重载不会长出两份。入口的 `key` 与 `url_name` 是契约。
- **身份目录不存数据、不判权限、不做授予**：四种 `GLOBAL` 身份由管理员授予、两种 `OBJECT` 身份由
  业务动作产生，这个区别决定了后台给不给分配入口。
- **入口过滤的三层顺序**：未登录或 `must_change_password=True` → 一个入口都没有；然后才轮到
  `staff_only` / `required_permission` / `visible_when`。

## 3. 已知限制 / 当前不支持

- **「只追加」拦的是行级 `UPDATE` / `DELETE`，不是整表**：`TRUNCATE`（含 `manage.py flush`）、
  `DROP TABLE`、从备份恢复、`ALTER TABLE`（删列、改类型——值没了而触发器一声不吭）与表继承同样绕过；
  `ALTER TABLE … DISABLE TRIGGER` 与 superuser 会话 `SET session_replication_role = replica`
  是敞开的逃生口（见 [`../docs/更新维护/开发与部署.md`](../docs/更新维护/开发与部署.md) §6）。
  保证的是「应用账号改不动、也删不掉单条留痕」，不是「谁都毁不掉」。
- **`rehome` 当前没有生产调用点**：`0002` 迁移刻意自带一份冻结实现（迁移要冻结当时的行为，
  不能跟着 `core.storage` 演进）。它的幂等与「缺文件只警告」是给运维脚本准备的。
  **别按 docstring 以为它天天在跑。**
- **注册表不跨进程共享，也没有持久化**：`unregister_entry` 是测试专用，生产代码没有注销入口。
- **坏入口只会被静默隐藏**：`visible_when` 的异常、反解不出的 URL 都只落在日志里，页面不会报错，
  也没有监控。
- **`require` 只在日志里留痕**：不写审计、不给用户一句「为什么不行」，403 页面是统一的。
- **`MultipleImageField` 对空值返回空列表**：父类的必填判定被绕过，`required=True` 是个不会生效的
  声明，必填由调用方自己的 `clean_*` 明说。
- **`get_client_ip` 默认不信 `X-Forwarded-For`**：反代下没打开 `TRUST_FORWARDED_FOR`，审计里所有来源都是
  代理地址，而 axes 的按 IP 锁定会把全站用户算成同一个人。这个开关**只在 nginx 确实会覆写该头时才该打开**。
- **core 不提供页面，也不替调用方开事务**：它没有 `views.py` / `urls.py` / `services.py` / `selectors.py`。
- **两条测试是平台级验收而非 core 的私有件**：`UploadChannelsRejectBombsAcceptanceTests` 会 import
  别的 app 的表单与服务，`UserSuppliedTextLimitAcceptanceTests` 会读别的 app 的模型字段——校验器住在 core、
  入口在别处，「改了一处、漏了一处」只有走真实入口才看得出。**测试代码跨 app import 是允许的，生产代码不行。**

## 4. 由来

- **指纹为什么存在模型自己身上**：文件会跟着记录一起死，单开一张按文件名索引的旁表会在每条路径上留下
  没人清理的孤儿行。字段跟着行走，删记录即删指纹。
- **`core.storage.rehome` 为什么留着**：给它下一次搬家用的——「受保护上传件搬家」那条迁移刻意另写了
  一份冻结实现，因为迁移不能依赖会变的代码。
