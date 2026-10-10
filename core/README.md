# core 模块

> 平台横向底座：跨应用权限口径（`is_admin` / 视图门槛 `require`）、审计日志、操作入口注册表、
> 身份目录、通用上传校验、文件指纹、受保护件的存储与取件出口，以及成员中心的概览计数。
> 它**只有一张表**（`AuditLog`），**没有页面**（没有 `views.py` / `urls.py` / `services.py` / `selectors.py`），
> 也**不产出任何业务判定**——「谁能做什么」仍归各 app 的 `permissions`，这里只统一口径与样板。
> 所有 app 都依赖它；它不在加载期依赖任何业务 app（唯一触到业务代码的地方是 `stats.py` 的函数内局部 import）。

**什么时候看**：加一个成员入口、写审计、给视图加权限门槛、调上传校验或大小上限、
动文件存储与取件响应、加一种身份、改后台的只读名册，或改成员中心的概览数字时。

---

## 1. 职责与边界

**负责**（都在 `core/` 下）：

| 东西 | 代码坐标 |
|---|---|
| 「谁算管理员」与视图门槛的样板 | `permissions.py` |
| 审计：`AuditLog` 表、`record_audit()`、全站唯一的取来源 IP 口径 `get_client_ip()` | `models.py`、`audit.py` |
| 操作入口注册表（成员中心的入口卡片）与顶栏当前栏目 | `registry.py`、`context_processors.py` |
| 身份目录：身份有哪几种、叫什么、从哪来（`Scope` / `Role`） | `roles.py` |
| 跨应用共用的上传校验：扩展名、读指针复位、按二进制内容验图片 | `uploads.py` |
| 上传件指纹：`sha256_of()` 与 `FileDigestMixin` | `hashing.py` |
| 受保护件的存储：`private_storage`、uuid 落盘名、两个根之间的搬移 | `storage.py` |
| 受保护件的取件响应（含两个指纹头） | `downloads.py` |
| 跨应用共用的表单件（一个字段收多个文件） | `forms.py` |
| 后台共用件：只读 mixin、姓名列、身份名册基类、`AuditLog` 的只读屏 | `admin.py` |
| 成员中心的平台概览计数 | `stats.py` |
| 模板过滤器与标签：`file_url`、`basename`、`file_ext`、`language_url` | `templatetags/` |
| 本模块自己的入口登记（`core.audit`，指向后台的审计日志屏） | `apps.py` |
| 建表与受保护件从公开根搬进受保护根的迁移 | `migrations/` |

**明确不做**——划出去的事，各自落在哪：

| 不在这里 | 落在哪 |
|---|---|
| 「谁能做什么」的业务判定 | 各 app 的 `permissions.py`（`reviews` / `projects` / `discussion` …）。`core.permissions` 只有 `is_admin` 与门槛样板，**在这里新写一条业务判定就是开出第二处真相** |
| 入口的可见判据 | 注册表只按条件过滤与排序，`visible_when` 传进来的是各 app 自己的判定函数 |
| 身份怎么授予、存在哪 | 授予在 `accounts.services.set_qualification` 与后台批量动作；存储在 `User` 的布尔字段与 `ProjectGroup.leader` / `members`；`roles.py` 只登记目录，不存第二处数据 |
| 请求 ID、强制改密、安全响应头、请求日志 | `config/middleware.py`（在 `config` 包，不在 core） |
| 公共装配：`INSTALLED_APPS`、两个 context processor、`AXES_CLIENT_IP_CALLABLE`、`PRIVATE_MEDIA_ROOT` / `TRUST_FORWARDED_FOR` | `config/settings.py` |
| 后台首页的「身份管理」分组 | `config/admin.py`（它硬编码六张名册的清单，顺序要和 `core.roles` 的 `sort_order` 保持一致） |
| Nginx 直出的公开媒体库 | 公开件落 `MEDIA_ROOT`（`mediafiles/`，`MEDIA_URL = "/media/"`）；`core.downloads` 只管受保护件的取件 |
| 六个取件视图本身（头像／图册／帖子图／项目书／批注版／归档版） | `accounts.file_views` / `discussion.views` / `projects.views` / `reviews.views`；**权限判定在各自的视图里**，core 只负责把响应拼对 |
| 各入口的上限与文案（项目书 20 MB、头像 2 MB……） | 各 app 的 `validators.py`；core 的 `validate_image_upload` 只收下 `label` 与 `max_bytes` |

**上游依赖**：`django`（`contrib.auth` / `contrib.admin` / `core.files.storage`）、`Pillow`。

**下游消费者**：

| 依赖方 | 依赖什么 |
|---|---|
| 所有业务 app | `core.permissions`（`is_admin` / `require`）与 `core.audit.record_audit` |
| 各 `AppConfig.ready()` | `core.registry.register_entry`；`accounts` 与 `projects` 另在那里登记 `core.roles` |
| 带**受保护件**的 app（`accounts` / `projects` / `reviews` / `discussion`） | `core.uploads` / `core.storage` / `core.hashing` / `core.downloads` 四个一起用 |
| `media`（公开件） | 只用 `core.uploads` 的图片校验与 `core.hashing` 的指纹——它不落受保护根、也没有取件视图 |
| `accounts` | `core.admin` 的共用件、`core.stats`、`core.forms`；`accounts.views` 是 `platform_overview` 的唯一调用点 |
| `discussion` / `content` | `core.forms` 的多文件字段；`core.admin` 的 mixin |
| 模板 | 三处 `{% load files file_urls %}`：文件控件的「当前文件」区块、`projects/group_detail.html`、`projects/group_manage.html` 取 `file_url` / `basename` / `file_ext`；`templates/base.html` 用 `language_url` 与 `nav_section` |

---

## 2. 关键接口与失败模式

**权限口径**（`permissions.py`）：

| 入口 | 语义 | 前置条件 | 失败模式 |
|---|---|---|---|
| `is_admin(user)` | 平台管理员：`is_staff` 或 `is_superuser` | 允许传 `None` / `AnonymousUser` | 不抛；三者皆假时返回 `False`。**别在别处再写 `user.is_staff`** |
| `require(request, predicate, event, **fields)` | 视图门槛：`predicate` 为假时记一条 warning 再抛 `PermissionDenied` | `predicate` 是**已求值的布尔值**（不是函数，调用方先算好，如 `can_manage_group(request.user, group)`） | 抛 `PermissionDenied` → 页面 403；warning 的格式是 `"%s username=%s%s path=%s"`，`fields` 按 `key=value` 追加在用户名之后，带 `extra={"request_id": ...}`（缺省 `"-"`）；**不写审计**（审计记的是写操作与登录锁定这类安全事件，被拒绝的视图请求不在其中）；通过时返回 `None`，不要拿它当布尔用 |

**审计与来源 IP**（`audit.py`）：

| 入口 | 语义 | 前置条件 | 失败模式 |
|---|---|---|---|
| `record_audit(*, action, user=None, target=None, detail=None, request=None)` | 写一条审计并返回该行；同时记一条 `audit.record` info 日志 | 全参数**只收关键字**；`action` 用已发布的稳定字符串；`detail` 只放**非敏感**结构化信息；`target` 是已入库的模型实例 | 位置传参 → `TypeError`；匿名 / 未登录的 `user` 落库为 `NULL`（外键 `SET_NULL`，删用户不删记录）；未入库的 `target` 会把 `target_id` 记成 `"None"`；`detail` 必须是可 JSON 序列化的值；数据库错误照常抛 |
| `get_client_ip(request)` | 全站唯一的来源 IP：默认只信 `REMOTE_ADDR`；`TRUST_FORWARDED_FOR` 打开时取 `X-Forwarded-For` 的**最后一段** | — | `request=None` → `None`；转发头为空 → 回退 `REMOTE_ADDR`。**`settings.AXES_CLIENT_IP_CALLABLE` 指着它**，改这里会同时改「锁了谁」与「记了谁」 |

**操作入口注册表**（`registry.py`）：

| 入口 | 语义 | 前置条件 | 失败模式 |
|---|---|---|---|
| `register_entry(*, key, label, description, url_name, required_permission=None, visible_when=None, staff_only=False, sort_order=100)` | 按 `key` 登记或覆盖一个成员入口，返回 `OperationEntry` | 在 `AppConfig.ready()` 里调用；`key` 全局唯一且稳定 | 按 `key` 幂等，重复登记只覆盖（开发自动重载会跑多次）；两个 app 用了同一个 `key` 就是互相覆盖，不报错 |
| `unregister_entry(key)` | 删掉一个入口 | **测试专用** | 不存在时静默返回 |
| `get_registered_entries()` | 全部入口，按 `(sort_order, key)` 排序 | — | 只读，返回元组 |
| `get_entries_for_user(user)` | 当前用户**可见且可反解**的入口 | — | 未登录或 `must_change_password=True` → `()`；`staff_only` 走 `is_admin`、`required_permission` 走 `user.has_perm`；`visible_when` 抛异常 → 记 `operation_registry.visibility_error` 并**隐藏该入口**；`url_name` 反解不出 → 记 `operation_registry.invalid_url` 并跳过 |
| `OperationEntry.url`（属性） | 反解地址 | `url_name` 已在路由里 | 反解失败原样抛 `NoReverseMatch`；`get_entries_for_user` 会接住它 |

**身份目录**（`roles.py`，只登记元数据）：

| 入口 | 语义 | 前置条件 | 失败模式 |
|---|---|---|---|
| `register_role(*, key, label, summary, scope, sort_order=100)` | 登记或覆盖一种身份 | `scope` 取 `Scope.GLOBAL`（管理员授予）或 `Scope.OBJECT`（业务动作产生） | 按 `key` 幂等；`label` / `summary` 一律写中文原样、**不进翻译**（只出现在 `/admin/`，后台不在双语范围内） |
| `get_roles()` | 全部身份，按 `(sort_order, key)` 排序 | — | 返回元组；后台分组的顺序由它固定 |
| `get_role(key)` | 取一种身份 | — | 没登记 → `None` |

**上传校验**（`uploads.py`）：

| 入口 | 语义 | 前置条件 | 失败模式 |
|---|---|---|---|
| `validate_image_upload(uploaded_file, *, label, max_bytes, extensions=IMAGE_EXTENSIONS)` | 一张图的完整校验：非空 → 扩展名 → 大小 → MIME 家族 → **按二进制内容**确认它真是图 | `label` 是给用户看的名字（进文案，前台的 label 要传译文）；`max_bytes` 是调用方自己的上限 | 一律抛 `ValidationError`，消息可直接展示；解压炸弹（`Image.DecompressionBombError`）与改了扩展名的伪图都在这里翻成表单错误，**不 500**；读的是上传流的副本，**校验完上传文件仍然可用**（调用方后面还要落盘） |
| `file_extension(name)` | 小写、不带点的扩展名 | — | 无扩展名 → `""` |
| `reset_file_position(uploaded_file)` | 把读指针拨回开头 | — | 不支持 `seek` 的对象（内存文件、测试替身）**安静跳过**，不抛 |
| 常量 `MAX_IMAGE_PIXELS` / `IMAGE_EXTENSIONS` | 像素总数上限；平台接受的图片扩展名（各调用方默认共用这一份，也可以自己传 `extensions`） | — | `MAX_IMAGE_PIXELS` 由本模块自己判，**不依赖 Pillow 的两档行为**（介于半倍与一倍之间只发 warning 的那一档会放行炸弹图，等页面渲染才解码） |

**文件指纹**（`hashing.py`）：

| 入口 | 语义 | 前置条件 | 失败模式 |
|---|---|---|---|
| `sha256_of(file_obj)` | 分块算已打开文件的 SHA-256，返回小写十六进制 | 调用方负责把指针放在想算的起点 | 从当前位置**读到末尾**（指针自然被推到末尾，它自己不复位——要接着读就由调用方 `seek(0)`）；分块是为了不把 500 MB 的视频整份读进内存 |
| `FileDigestMixin.save()` | 每次保存让 `sha256` 跟上文件；子类声明 `digest_field` | 子类**必须**声明 `digest_field` | 没声明 → `ImproperlyConfigured`（刻意的：宁可当场炸，也不要指纹静默失效）；`save(update_fields=[…])` 带了文件列 → 把 `sha256` 并进写入列表；**没带文件列 → 不动指纹**；文件不在盘上 → 记 `file_digest.missing` warning、返回空串，**保存照常成功** |

**存储**（`storage.py`）：

| 入口 | 语义 | 前置条件 | 失败模式 |
|---|---|---|---|
| `private_storage` / `PrivateStorage` | 受保护件的存储实例，`location` 取 `settings.PRIVATE_MEDIA_ROOT` | — | `url()` 返回**空串**（不抛异常：框架的 `ClearableFileInput.is_initial()` 会真的求值它，抛出去就是模板渲染 500）；不给公开地址 |
| `neutral_upload_to(prefix)` / `NeutralUploadTo` | 落盘名换 uuid + 按年月分目录，保留扩展名 | `prefix` 是本类的子目录名 | 写成类（`@deconstructible`）是为了能序列化进迁移，闭包做不到 |
| `ProtectedClearableFileInput` | 文件控件的「当前文件」区块按**有没有文件名**判断 | 表单字段要显式指定这个 widget | Django 原版按 `url` 判断，受保护件没有 URL，那一块会整个消失（用户看不到已传的件、也没有清除勾选框） |
| `delete_stored_files(files)` | 事务回滚后删掉本次已落盘的 `(storage, name)` | 只在回滚路径上用 | 逐个 `delete`；数据库回滚不会把文件带回去，所以「一个事务连写多个文件」的写命令要自己记账 |
| `rehome(file_field, *, private)` | 把一个已存文件在两个根之间搬一次，返回相对路径（两个根的相对路径相同，字段值因此不用改） | — | 文件不存在 → 记 `private_media.missing` warning 并返回原路径（不让整条迁移挂掉）；目标已存在 → 记 `private_media.already_there` 且**不覆盖**（幂等）。**当前没有生产调用点**，`0002` 迁移刻意另写了一份冻结实现 |

**取件**（`downloads.py`）：

| 入口 | 语义 | 前置条件 | 失败模式 |
|---|---|---|---|
| `serve_file(file_field, *, download_name, as_attachment, sha256="")` | 把存储里的文件送出去，按 `sha256` 挂指纹头 | **权限判定在调用方**（视图先判可见性再调它）；`sha256` 留空表示这份文件没有指纹（图片类、历史数据） | 文件不在盘上 → `Http404`（**不是 500**：运维挪过文件、备份不完整都会走到这一支，500 会把路径写进错误页）；MIME 按落盘扩展名猜，猜不到给 `application/octet-stream`；没有指纹 → 只发文件；指纹畸形或长度不对 → 记 `file_digest.invalid` / `file_digest.unexpected_length` warning 并**只发文件**，绝不编一个值出来 |

**表单件、模板与上下文**：

| 入口 | 语义 | 前置条件 | 失败模式 |
|---|---|---|---|
| `forms.MultipleImageField` / `MultipleFileInput` | 一个字段收多个文件，`cleaned_data` 是列表 | 类型与大小由调用方把校验器传进来（讨论区 3 MB、获奖图 10 MB……） | 空值直接返回空列表、**绕过父类的必填判定**——写 `required=True` 也不会生效，必填要调用方自己判；逐个 clean，第一个失败就中断整批（批量上传要逐张报出文件名时，判定得挪到服务层） |
| `templatetags.file_urls.file_url` | 文件字段的公开地址 | 模板里取受保护件**只能用这个** | 受保护件（`url()` 给空串）或空字段 → `""`，让 `{% if %}` 安静判断；**不要在模板里写 `{{ field.url }}`**（空字段会抛 `ValueError`） |
| `templatetags.files.basename` / `file_ext` | 路径的文件名 / 大写扩展名（文件类型角标用） | — | `file_ext` 对无扩展名返回 `FILE` |
| `templatetags.language_urls.language_url` | 当前页在指定语言下的地址（含查询串），顶栏语言切换用 | 模板要拿得到 `request` | 解析不出别的语言版本 → 返回原地址（宁可点了没反应，也不给不存在的链接）；拿不到 `request` → 返回空串 |
| `context_processors.operation_entries` | 把注册表过滤后的入口注入每个模板 | 挂在 `config.settings` 的 `TEMPLATES` 上 | 见 `get_entries_for_user`；模板在 `templates/accounts/member_home.html` 里遍历渲染 |
| `context_processors.nav_section` | 顶栏当前栏目：`NAV_BY_VIEW` 按视图名查，未列出的成员视图按命名空间回退到 `member` | — | 查不到 → `""`（顶栏不标任何栏目）；纯展示，不做判定 |

**后台共用件与概览计数**：

| 入口 | 语义 | 前置条件 | 失败模式 |
|---|---|---|---|
| `admin.ReadOnlyAdminMixin` | 只读：`has_add_permission` / `has_change_permission` 都为假 | — | **不覆写 `has_delete_permission`**——各模型的删除口径本就不同，一并改掉会动到既有行为 |
| `admin.ProfileNameMixin` | 列表页的「姓名」列，取 `profile__full_name` | — | 账号必须有一份 `Profile`（由 `accounts` 的信号保证） |
| `admin.RoleRosterAdmin` | 身份名册基类：只读、能搜、顶上说明这个身份从哪来 | 子类给 `role_key`（取 `core.roles` 的登记）、`list_display`、`get_queryset` | 对象身份**不提供任何分配入口**；`role_key` 没登记 → 说明留空 |
| `stats.can_view_platform_overview(user)` | 概览数字给谁看：管理员或项目组联系人 | — | 未登录 → `False`；「谁算联系人」委托 `projects.permissions`（函数内局部 import，避免加载期牵连） |
| `stats.platform_overview()` | 四个计数：在册人数、项目组数、开放竞赛数、在借设备数 | — | 不做缓存（社团规模下四条 COUNT 足够便宜）；数字**不对外公开**，只出现在成员中心 |

---

## 3. 状态与不变量

### AuditLog

| 字段 | 决定什么 |
|---|---|
| `action` | 操作名。**一旦发布就不再改**，历史记录要保持连续 |
| `user` | 操作者，`SET_NULL`：用户被删，记录仍在，操作者变成 `NULL` |
| `target_type` / `target_id` | `"<app_label>.<model_name>"` 与 `str(pk)`；**字符串列**，所以被删对象也留得下标识 |
| `detail` | JSON，只放非敏感结构化信息（口令、Cookie、完整请求体从不进这里） |
| `request_id` | 关联请求（`config.middleware.RequestLoggingMiddleware` 设的 `request.request_id`），没有请求时为空串 |
| `ip_address` | 来源 IP，口径是 `get_client_ip` |
| `created_at` | `auto_now_add`；`Meta.ordering` 与按时间读的那两个索引都是倒序，另有 `(target_type, target_id)` 索引供按目标反查 |

- **审计只追加**：模型层没有任何写保护，**唯一的执行点是 `AuditLogAdmin`**——新增、修改、删除三个权限全为假（删是唯一一条明确禁删的只读记录）。新开一条改审计路径，这条不变量就破了。
- **`record_audit` 不体检 `detail`**：「只记非敏感信息」靠调用方自律，没有任何运行时过滤。
- **审计的事务边界由调用方决定**：`core` 不替调用方开事务——跟写操作同事务还是提交之后写，取决于调用点怎么安排（各 app 的做法见各自的 README）。

### FileDigestMixin

- **指纹字段跟着行走**（`sha256` 存在模型自己身上，不单开旁表）：文件会跟着记录一起死（换头像删旧图、删图册删盘、帖子图随编辑被替换），旁表会在这些路径上留下没人清理的孤儿行。字段本身是 `editable=False`——**不进任何表单**，只能由 `FileDigestMixin` 维护。
- **接了七个文件字段**：项目书（`projects`）、批注版与归档版（`reviews`）、头像与图册（`accounts`）、帖子图（`discussion`）、媒体库（`media`）。新增带文件字段的模型时照这个清单补。
- **`digest_field` 只认一个文件字段**：平台上每个模型都只有一个；真有第二个时再把字段名变成参数。
- **三种情形三种算法**（`_file_sha256`）：**刚上传、还没落盘**（`_committed` 为假）读的就是上传流，不必等落盘再读一遍；**已落盘且已有指纹**沿用（改一句简介不该重读 20 MB 的项目书）；**已落盘、指纹为空**（迁移前的老数据）从存储补算一次，此后一直沿用。
- **算完必须把上传流拨回开头**，否则紧接着的落盘会存下一个空文件。
- **`save(update_fields=[…])` 的两条规则**：带了文件列 → 算出的指纹**与现值不同**时会把它并进写入列表（换头像走的正是 `save(update_fields=["avatar", "updated_at"])`，不并进去就永远写不进去）；**没带**文件列 → 完全不动指纹（Django 不会落盘那个新文件，照内存里的内容重算就会与库里的文件对不上）。指纹没变就别硬塞——有一条用例专门钉这个。
- 指纹**按存储里的字节算、与文件名无关**：受保护件的落盘名已换成 uuid（原文件名不保存），公开件（媒体库）则保留原文件名——两种情况下指纹都只认字节，所以换名、改名都不影响它。指纹因此是文件内容的身份，不是路径的身份。

### 存储的两类根

| 类别 | 落哪 | 谁负责取 | 代号 |
|---|---|---|---|
| 公开件 | `MEDIA_ROOT`（`mediafiles/`） | Nginx 直出 `/media/`，本来就不该有权限判定 | `MEDIA_URL = "/media/"` |
| 受保护件 | `PRIVATE_MEDIA_ROOT`（`protected_media/`，**刻意不在前者的目录树之下**） | 只经视图，权限判定才有意义 | `private_storage` |

- **两个根里的相对路径相同**：所以 `rehome` 搬完之后数据库字段一个字都不用改，迁移也因此天然幂等。
- **真正的屏障是目录边界，不是 `url()`**：`PrivateStorage.url()` 返回空串只是「别拼地址」的软约束；受保护件不在 `mediafiles/` 之下，Nginx 的 `/media/` 永远指不到它们。**把 `PRIVATE_MEDIA_ROOT` 挪进 `MEDIA_ROOT`，全部取件判定立刻失效，而页面上看不出来。**
- **落盘名与用户填的名字彻底脱钩**：`neutral_upload_to(prefix)` 换成 uuid 并按年月分目录，只保留扩展名——原文件名会带人名、组名、项目名，而它会跟着文件走进备份、运维的 `ls` 与下载头。

### 注册表与目录

- **注册表是进程内的内存态**（`_ENTRIES` + `RLock`），靠各 `AppConfig.ready()` 在启动时填充；按 `key` 幂等，所以开发自动重载不会长出两份。入口的 `key` 与 `url_name` 是契约。
- **两个注册表同一套形状**（frozen dataclass + 幂等注册 + `RLock`）：操作入口用 `OperationEntry`，身份用 `Role`；排序都取 `(sort_order, key)`，同分按 key 兜底。
- **身份目录不存数据、不判权限、不做授予**：四种 `GLOBAL` 身份由管理员授予、两种 `OBJECT` 身份由业务动作产生，区别决定了后台给不给分配入口（见 [../docs/architecture/permissions.md](../docs/architecture/permissions.md) §7.1.1）。
- **唯一的表是 `AuditLog`**：core 没有业务模型，也没有 schema 之外的持久状态（注册表与目录都是内存里的）。

---

## 4. 数据流与时序

**一次取件**（六个取件视图共用）

1. 视图先自己把门槛走完：`@login_required` + 业务判定（`require(...)`、`can_view_group`、匿名 302 去登录页）。
2. 调 `serve_file(file_field, download_name=..., as_attachment=..., sha256=...)`；`file_field.open("rb")` 打开文件。
3. 文件不在盘上 → `Http404`（接住 `FileNotFoundError`，不冒成 500）。
4. `mimetypes.guess_type(file_field.name)` 按落盘扩展名猜 content type，猜不到给 `application/octet-stream`；`FileResponse` 用 `download_name` 拼下载名。
5. `sha256` 非空且合法 → 挂两个头：`Content-Digest`（RFC 9530，base64）与 `X-Checksum-SHA256`（十六进制，与 `sha256sum` / `certutil -hashfile` 的输出一字不差）。**`serve_file` 自己不现算指纹**——值来自模型上的 `sha256` 字段，或干脆不传。
6. 响应返回，字节从存储流出；Nginx 全程不参与。

**一次指纹计算**（任意带文件字段的模型保存时）

1. 子类调 `save()` 落到 `FileDigestMixin.save()`；先查 `digest_field`，没声明直接 `ImproperlyConfigured`。
2. `update_fields` 给了且**不含**文件列 → 直接交给 `super().save()`，指纹一个字都不碰。
3. 否则进 `_file_sha256()` 三选一：未落盘 → 复位上传流 → `sha256_of()` → **再复位**；已落盘且已有指纹 → 沿用；指纹为空 → `storage.open(name, "rb")` 补算（`FileNotFoundError` → `file_digest.missing` warning + 空串）。
4. 新旧指纹不同才赋值；`update_fields` 非空时把 `sha256` 并进写入列表。
5. `super().save()` 落盘并写库——换头像这条路上，写进去的指纹与刚落的文件是同一次保存。

**一次入口装配**（每个成员页面）

1. 各 app 在 `AppConfig.ready()` 里 `register_entry(...)`；`sort_order` 越小越靠前，默认 100。
2. `core.context_processors.operation_entries` 每个请求调 `get_entries_for_user(request.user)`。
3. 过滤顺序：未登录或 `must_change_password=True` → 这一人一个入口都没有；`staff_only` 问 `is_admin`；`required_permission` 问 `user.has_perm`；`visible_when` 调各 app 自己的判定（抛异常 → 记日志并隐藏）。
4. 剩下的逐个反解 `OperationEntry.url`，反解不出的跳过并记日志。
5. 按 `(sort_order, key)` 排序返回；`templates/accounts/member_home.html` 遍历 `operation_entries` 渲染卡片。

（`nav_section` 是另一条独立的路：按视图名/命名空间算顶栏该高亮哪个栏目，纯展示、不涉及权限。）

**一次审计写入**

1. 视图或服务调 `record_audit(action=..., user=..., target=..., detail=..., request=...)`。
2. `target` → `target_type = "<app_label>.<model_name>"`、`target_id = str(pk)`。
3. `request_id = request.request_id`（没有请求时空串）；`ip_address = get_client_ip(request)`。
4. `AuditLog.objects.create(...)`，紧接着一条 `audit.record` info 日志（带 `request_id`）。
5. 是否在事务内、什么时候提交，全看调用点——core 不加事务、不重试、不吞异常。

---

## 5. 错误处理与诊断

**拒绝形态**（页面上的实际表现）：

| 情形 | 表现 |
|---|---|
| `require` 的 `predicate` 不成立 | warning 日志（`event` 前缀 + `username=` + `fields` + `path=`）→ `PermissionDenied` → **403**；页面上不解释为什么 |
| 按对象判可见性的取件（项目书／批注版／归档版／帖子图） | **403**（各视图里的 `PermissionDenied`）；通知详情是另一类口径，越权一律 **404**，见 [../docs/architecture/overview.md](../docs/architecture/overview.md) §4 |
| 受保护文件在盘上缺失 | **404**（`serve_file` 把 `FileNotFoundError` 转掉），不是 500 |
| 上传件不合格（含几十字节的解压炸弹） | 各表单/服务的 `ValidationError` → 表单错误或 `messages.error`；`core.uploads` 保证**不 500、不落盘** |
| 入口的 `visible_when` 抛异常 | 该入口隐藏，页面照常渲染；日志 `operation_registry.visibility_error` |
| 入口的 `url_name` 反解不出 | 该入口跳过；日志 `operation_registry.invalid_url` |
| 指纹参数畸形 | 只发文件、不挂头；日志 `file_digest.invalid` / `file_digest.unexpected_length` |

**日志事件**（`logging.getLogger(__name__)`；`config.settings` 里 `core` 这个 logger 是 DEBUG 级）：

| 事件 | 出处 |
|---|---|
| `audit.record` | `record_audit` 每写一条（含 `audit_id`、`target`、`actor`） |
| `operation_registry.register` / `.unregister` / `.resolve` | 入口登记与每次过滤结果（DEBUG） |
| `operation_registry.visibility_error` / `.invalid_url` | 两种「悄悄跳过」，都带 `logger.exception` |
| `role_registry.register` | 身份登记（DEBUG） |
| `file_digest.missing` | 库里指着、盘上没了 |
| `file_digest.invalid` / `file_digest.unexpected_length` | 指纹头发不出去 |
| `private_media.already_there` / `.moved` / `.missing` | 只有 `rehome`（`core/storage.py`）会发这三条 |
| `private_media.rehome`（汇总）与迁移自带的 `private_media.missing` | `core/migrations/0002_rehome_protected_uploads.py`——搬迁迁移**另写了一份冻结实现**，所以它发的 `missing` 与上面那条同名但字段不同，且它**不发** `.moved` / `.already_there` |

**刻意不报错**：重复登记同一个 `key` 的入口或身份 → 覆盖，不报错；
坏入口（`visible_when` 抛异常、`url_name` 反解不出）→ 隐藏/跳过，一个坏入口不带垮整页；
`reset_file_position` 遇到不支持 `seek` 的对象 → 安静返回；
老数据指纹为空、文件不在盘上 → `file_digest.missing` warning，保存照常成功；
`rehome` 目标已存在 → 当作已就位，文件缺失 → warning + 返回原路径；
`serve_file` 的指纹为空 → 只发文件，**不编一个值出来**（错的校验值比没有校验值更坏）。

---

## 6. 测试要点与已知限制

### 测试

| 文件 | 钉住什么 |
|---|---|
| `tests/test_registry_and_audit.py` | 各 app 登记了哪些入口、按权限与改密状态过滤、登记幂等与排序；审计行落库的 actor/target/request_id/detail；`AuditLogAdmin` 三项权限全假；`get_client_ip` 的分支（默认不信转发头、开关打开才读、只取最后一段、空头回退） |
| `tests/test_upload_validation.py` | 解压炸弹一律翻成 `ValidationError`（含 Pillow 半倍与一倍之间那一档）、校验不破坏调用方手里的上传流、四条真实上传通道（头像表单／图册服务／帖子表单／媒体库）都不 500、成员可填长文本的长度上限逐项核对 |
| `tests/test_hashing.py` | 分块算法的正确性与块边界、结果与 `hashlib` 一致；`digest_field` 未声明当场炸；三种情形各自的分支；`update_fields` 的两条规则与「指纹没变就别硬塞」；文件缺失不编指纹 |
| `tests/test_downloads.py` | 两个指纹头的写法、响应体就是原文件字节、无指纹只发文件、畸形指纹不 500、文件不在盘上 404 |
| `tests/test_interface_translation.py` | 源码里 `gettext` 的文案在 `en` 目录里都有非空译文、占位符对得上、复数条目两条、没有 `fuzzy`、没有在模块/类体里给惰性译文插值 |

这套测试里有两条是**平台级验收**而非 core 的私有件：`UploadChannelsRejectBombsAcceptanceTests` 会 import 别的 app 的表单与服务，`UserSuppliedTextLimitAcceptanceTests` 会读别的 app 的模型字段——校验器住在 core，入口在别处，「改了一处、漏了一处」只有走真实入口才看得出。测试代码跨 app import 是允许的，生产代码不行。

### 已知限制 / 当前不支持

- **审计的「只追加」靠后台类守，没有数据库约束**：模型层能改能删。绕过 `AuditLogAdmin` 的代码路径（数据修复、脚本、`queryset.update()`）不受任何保护。
- **`record_audit` 不检查 `detail` 的内容**：写进去什么就永久留什么，敏感信息靠调用方自律。
- **`PrivateStorage.url()` 不是访问控制**：它只返回空串。真正的保障是 `PRIVATE_MEDIA_ROOT` 不在 `MEDIA_ROOT` 之下 + Nginx 只映射后者；把两个根配到一起，页面上不会有任何异常提示。
- **`rehome` 当前没有生产调用点**：`0002` 迁移刻意自带一份冻结实现（迁移要冻结当时的行为，不能跟着 `core.storage` 演进）。它的幂等与「缺文件只警告」是给运维脚本准备的。
- **注册表是进程内的内存态**：不跨进程共享，也没有持久化；`unregister_entry` 是测试专用，生产代码没有注销入口。
- **坏入口只会被静默隐藏**：`visible_when` 的异常、反解不出的 URL 都只落在日志里，页面不会报错，也没有监控。
- **`require` 只在日志里留痕**：不写审计、不给用户一句「为什么不行」，403 页面是统一的。
- **`MultipleImageField` 对空值返回空列表**：父类的必填判定被绕过，`required=True` 是个不会生效的声明，必填由调用方自己的 `clean_*` 明说。
- **`FileDigestMixin` 一个模型只能有一个文件字段**：`digest_field` 是单个字段名。
- **`get_client_ip` 默认不信 `X-Forwarded-For`**：反代下没打开 `TRUST_FORWARDED_FOR`，审计里所有来源都是代理地址，而 axes 的按 IP 锁定会把全站用户算成同一个人。这个开关**只在 nginx 确实会覆写该头时才该打开**。
- **core 不提供页面，也不替调用方开事务**：它没有 `views.py` / `urls.py` / `services.py` / `selectors.py`；「审计跟写操作同事务还是提交后写」是调用点的决定。
