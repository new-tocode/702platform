# accounts 模块

> 账号与成员身份：自定义 `User`（`AUTH_USER_MODEL`）、`Profile`、个人图册、强制改密流程、
> 头像与图册的受保护取件，以及后台的四张全局身份名册。
> **它不判「谁能做什么」**（本 app 没有 `permissions.py`），也不管项目组与评审的业务规则——
> 资格、联系人、组员各自的判定都在别的 app。
> 所有业务 app 的用户外键都指向它，它是依赖图的根——**只有一处例外**：`accounts/admin.py` 在模块级 `from reviews import lifecycle`（两个资格名册要取 `STAGE_*` 常量），所以「不反向依赖」这句话是有例外的，见 §1 的依赖方向。

**什么时候看**：改账号字段、改登录／改密流程、动个人信息页、碰头像与图册、
改资格的批量授予入口，或者要给 `User` 加一个布尔字段时。

---

## 1. 职责与边界

**负责**（都在 `accounts/` 下）：

| 东西 | 代码坐标 |
|---|---|
| `User`（`AbstractUser` + 四个布尔字段）、`Profile`、`GalleryImage`、四张身份名册 proxy | `models.py` |
| 登录、登出、强制改密（首次与后续同一张页、两个表单）、改密后的 `next` 校验 | `views.py`、`forms.py`、`urls.py` |
| 公开首页 `accounts:home` 与成员中心 `accounts:member_home` | `views.py`、`templates/accounts/` |
| 个人信息页（资料表单 + 头像 + 身份清单 + 图册）与成员只读资料页 | `views.py`、`forms.py`、`selectors.py`、`roles.py` |
| 头像、图册的写命令与两个取件口 | `services.py`、`file_views.py` |
| 资格的**批量**授予／撤销、用户组成员的整份覆盖 | `services.py`、`admin.py` |
| 登录锁定的响应与审计 | `axes.py` |
| 上传件的上限与文案 | `validators.py` |
| 账号生命周期信号：`Profile` 自动创建、登录成功／失败日志 | `signals.py` |
| 后台：建号（姓名必填）、重置密码、用户与用户组编辑、四张只读名册与六个批量动作 | `admin.py` |
| 操作入口与四种全局身份的登记 | `apps.py` |

**明确不做**——划出去的事，各自落在哪：

| 不在这里 | 落在哪 |
|---|---|
| 「谁能做什么」的判定 | **本 app 没有 `permissions.py`**：管理员问 `core.permissions.is_admin`，项目组联系人／成员问 `projects.permissions`，评审资格问 `reviews.permissions`（`accounts.selectors` 只在函数体内局部 import 后者） |
| 评审资格怎么用（抽人、门槛、待办） | `reviews`；`accounts` 只存 `is_reviewer` / `is_preliminary_reviewer` / `is_super_reviewer` 三个字段，并提供后台批量写入口 |
| 强制改密的**拦截** | `config.middleware.ForcePasswordChangeMiddleware`：白名单只有 `accounts:password_change` 与 `accounts:logout`，`accounts` 只提供改密页和这个字段 |
| 登录失败计数、锁定判定、冷却时长 | django-axes + `config/settings.py` 的 `AXES_*`；`accounts.axes` 只把锁定响应换成站内中文页并写审计 |
| 项目书、批注版、归档版、帖子图的取件 | `projects.views` / `reviews.views` / `discussion.views`；`accounts.file_views` 只管头像与图册 |
| 上传校验实现、存储、取件响应、文件指纹 | `core.uploads.validate_image_upload`、`core.storage`、`core.downloads.serve_file`、`core.hashing.FileDigestMixin` |
| 内部通知的投递语义 | `notices`；`auth.Group` 的成员关系在这里维护，只当通知的收件范围，**不是身份** |
| 公开注册、自助找回密码 | 有意不做（`docs/architecture/overview.md` §1.1）；忘密码由管理员在后台重置 |

**上游依赖**：`django.contrib.auth`、`core.permissions` / `core.audit` / `core.registry` /
`core.roles` / `core.storage` / `core.uploads` / `core.hashing` / `core.downloads` / `core.stats`。
跨 app 的 import 基本都在函数体内（`projects.selectors`、`projects.permissions`、
`reviews.permissions`、`reviews.panels`、`notices.panels`、`content.models`），加载期不牵连它们。
**已知的一处例外**：`admin.py` 在模块级 `from reviews import lifecycle`（两个资格名册要用
`lifecycle.STAGE_*` 取阶段名）。今天不成环（`reviews/lifecycle.py` 不 import accounts），
但这是本 app 唯一一条加载期反向依赖——要动它先确认这一点。

**下游消费者**：`config.settings.AUTH_USER_MODEL` 指向 `accounts.User`；`projects` / `reviews` /
`discussion` / `notices` / `competitions` / `equipment` / `content` / `media` / `core` 的模型
一律以 `settings.AUTH_USER_MODEL` 或 `get_user_model()` 外键到它，**没有任何 app 的生产代码
直接 import `accounts`**。模板到处 reverse `accounts:home` / `login` / `logout` / `member_home` /
`member_profile` / `avatar_file` / `gallery_file`。`User` 的字段因此是平台级接口：加字段要在
`admin.py` 的 fieldsets 与各名册里交代清楚。

---

## 2. 关键接口与失败模式

| 入口 | 语义 | 前置条件 | 失败模式 |
|---|---|---|---|
| `services.set_qualification` | 批量授予／撤销一项资格，返回真正变化的账号数 | `flag ∈ QUALIFICATION_FLAGS`（三个评审资格） | 白名单外的 flag（如 `is_superuser`、`is_active`）→ `ValueError`；取值已相同的人被跳过，重复提交幂等且**不留审计**；HTTP 门槛只在 `@admin.action(permissions=["change"])` 上，漏声明则只挂 `view_user` 的只读观察者也能提交 |
| `services.set_group_members` | 把组员整份设成 `members`（覆盖，非增量），返回 `(added, removed)` | `group` 已存在 | 名单没变 → `((), ())` 且不写审计、不写库；`Group.objects.select_for_update()` 把并发保存串行化，后提交者读到的是前一次的结果（**用例是两次串行调用，真并发没有用例**） |
| `services.set_avatar` / `clear_avatar` | 换／删头像，连磁盘上的旧文件一起处理 | **`profile` 必须是数据库里取出来的那一份**，不是被表单改过的实例 | 实例若已经被表单改过，`profile.avatar.name` 读到的就是新图，旧文件会变成「删新文件」；本来没头像时 `clear_avatar` 返回 `False`（视图给 warning，不是异常） |
| `services.add_gallery_images` | 批量加图，返回 `GalleryBatchResult(added, rejected, overflowed, used_bytes)` | 至少选了一个文件 | 一个都没选 → `GalleryError`（视图翻成 `messages.error`）；单张不合格进 `rejected`、合计超 `GALLERY_TOTAL_MAX_BYTES` 进 `overflowed`，其余照加；中途异常 → 事务回滚 + `core.storage.delete_stored_files` 清掉已落盘的新文件 |
| `services.move_gallery_image` / `set_gallery_layout` / `delete_gallery_image` | 调顺序／改排布／删一张（连文件） | `direction ∈ {up, down}`；`layout ∈ LAYOUT_CHOICES` | 参数越界 → `ValueError`（编程错误；视图先自行判定，页面上的非法值一律 404）；已在头／尾 → 返回 `False`；排布没变 → 直接返回，不写审计 |
| `selectors.member_identities` / `gallery_usage` / `roles.describe_member` | 只读派生：身份清单（含组名）／图册用量／一个身份标签 | 只读，不写库 | 未登录时 `member_identities` 返回 `()`、`describe_member` 返回「游客」 |
| `file_views.avatar_file` / `gallery_file` | 受保护取件，经 `core.downloads.serve_file` | `@login_required` | 匿名 → 302 到登录页；没有头像 → 404；文件不在盘上 → `serve_file` 转 404 而不是 500；**不发指纹响应头** |
| `accounts:member_profile`（只读资料页） | 看另一位成员的公开资料 | 登录；目标 `is_active=True` | 目标不存在或已停用 → 404（不泄漏存在性）；非 GET → 405 |
| `accounts:profile` 与 `gallery_*` / `avatar_*` 视图 | 本人维护资料、头像、图册 | 登录；除 profile 页外都要 POST | 别人的图 → 404（先按 `profile=` 过滤再 `get_object_or_404`）；非法 `direction` / `layout` → 404；未登录 → 302 到登录页；`GET` 打 POST-only 视图 → 405 |
| `axes.lockout_response` | 锁定时的 403 页面 + `accounts.login.lockout` 审计 | 由 axes 在**口令校验之前**调用 | 正确口令同样进不来；`credentials` 只取用户名，口令从不进审计；状态码是 `LOCKOUT_STATUS = 403`（不是 429） |

---

## 3. 状态与不变量

### User

| 字段 | 决定什么 |
|---|---|
| `must_change_password` | 默认 `True`；为真时中间件把人限制在改密页与登出两条路上。`UserManager.create_superuser` 覆写为 `False`（否则 `createsuperuser` 建的管理员一登录就被关进改密页）。本人改密成功由 `PasswordChangeView` 关掉；管理员重置密码（`AdminPasswordChangeForm`）重新打开 |
| `is_reviewer` / `is_preliminary_reviewer` / `is_super_reviewer` | 判定不在这里（`reviews.permissions`）；这里是它们的**存储**与后台**批量**写入口。三个字段相互独立：超级评审不隐含评审资格 |
| `is_staff` / `is_superuser` / `is_active` | Django 原有字段；「谁算管理员」一律问 `core.permissions.is_admin`，不写 `user.is_staff` |
| `groups` | `auth.Group` 成员关系，只给内部通知当投递范围，**不是身份**、不进 `core.roles` 目录 |

### Profile（`OneToOne(User)`，`related_name="profile"`）

| 字段 | 决定什么 |
|---|---|
| `full_name` | 平台唯一用作「姓名」的字段；`User.first_name` / `last_name` 是弃用的历史列 |
| `avatar` | `private_storage` + `neutral_upload_to("avatars")`，≤2 MB（`validators.AVATAR_MAX_BYTES`） |
| `student_id` | `unique=True` 且 `null=True`：没填的账号落在 NULL 上，多个 NULL 不互相冲突——空值语义是 NULL，不是空串 |
| `bio` | ≤1000 字 |
| `sha256` | 由 `FileDigestMixin` 在保存时维护；换头像后重算，取件时不发给客户端 |

### GalleryImage（FK `Profile`，级联删除）

| 字段 | 决定什么 |
|---|---|
| `image` | `private_storage` + `neutral_upload_to("gallery")`，单张 ≤5 MB（`validators.GALLERY_IMAGE_MAX_BYTES`） |
| `layout` | `normal` / `wide` / `full`；宽屏下分别占 1／2／整行，窄屏下 `wide` 也铺满整行 |
| `sort_order` | 页面顺序；`Meta.ordering = ("sort_order", "id")`，历史数据撞号时按 id 兜底 |
| `file_size` | `save()` 时从 `image.size` 写入，`editable=False`；整册合计上限求和用它 |
| `save()` | 每次保存都跑 `full_clean()`——所以 `set_gallery_layout` 刻意走 queryset `update()`，换个排布不重读、不解码图片 |

### 必须成立的断言

- **上限分两层**：单张在 `validators.py` 的常量（模型字段与表单共用同一份），整册合计在
  `models.GALLERY_TOTAL_MAX_BYTES`（100 MB）。合计要跨行求和，模型与数据库都没有这条约束，
  **唯一的执行点是 `services.add_gallery_images`**；绕过它直接建 `GalleryImage` 可以超限。
- **头像与图册一律 `private_storage`**：`PRIVATE_MEDIA_ROOT` 刻意不在 `MEDIA_ROOT` 之下，
  Nginx 的 `/media/` 指不到。落盘名换成 uuid（原文件名会带人名，会跟着文件走进备份与运维的 `ls`）。
  模板取图走 `{% url 'accounts:avatar_file' %}` / `gallery_file`，**不写 `{{ field.url }}`**。
- **身份的唯一真相源是 `User` 上的布尔字段**：四张名册（`AdminRole` 等）是 proxy，不建表、
  不存第二处数据，所以不存在「名册与字段分叉」这种状态。
- **每个账号必有一份 `Profile`**：`post_save` 信号在 `created` 时补（`raw` 加载夹具时跳过）；
  建号早于该信号的历史账号由 `views._member_profile` 的 `get_or_create` 当场补齐并记日志。
- **审计的事务边界**（改之前先看清是哪一种，别按「一律」记）：`set_avatar`、`clear_avatar`、
  `gallery.add`、`gallery.delete` 的审计行与数据写在**同一个 `atomic` 里**；而
  **`set_qualification` 与 `set_group_members` 的审计在事务提交之后写**（数据先落、审计后写——
  两步之间进程挂掉会留下「资格改了但审计里没有」，这是既有行为，与 `projects`／`reviews`
  的口径一致）。`move_gallery_image` 只有重排在事务里、`set_gallery_layout` 完全不开事务——它们各只动一列。
- **文件系统不在事务里**：所有文件删除放在提交之后（失败顶多多留一个旧文件，不会出现
  「库里还指着、盘上没了」）；批量加图相反，中途失败要清掉这次已经落盘的新文件。
- **审计 action 字符串一旦发布就不再改**：`accounts.qualification.*` 等清单见 §5。

---

## 4. 数据流与时序

**建号 → 拿到 Profile**
1. 后台建号（`AdminUserCreationForm`）设置初始密码、`must_change_password = True`，
   并可当场勾三种评审资格（管理员身份不在此列，要建号后单独确认）。
2. `post_save` 信号补一份 `Profile`；表单再把 `full_name` 写进去（`save_profile`）。
3. `UserAdmin.save_model` 写 `accounts.user.create` / `accounts.user.update` 审计。

**首次登录 → 强制改密**
1. `PlatformLoginView.get_success_url`：`must_change_password` 为真 → 改密页（并记
   `auth.login.redirect`），否则走正常跳转。
2. 中间件 `ForcePasswordChangeMiddleware` 是硬闸门：除改密页与登出页外的所有路径都 302 回改密页
   （带 `next`），连 `/admin/` 也不放行。
3. `PasswordChangeView` 按 flag 选表单：首次用 `FirstPasswordChangeForm`（只收新密码），
   之后用 `MemberPasswordChangeForm`（要旧密码）。`form_valid` 里：关 flag →
   `update_session_auth_hash`（不踢出当前会话）→ 写 `accounts.password.change` 审计
   （`detail={"forced_flow": ...}`）→ `get_success_url` 只接受同站 `next`。

**换头像**（`services.set_avatar`）
1. 视图从库里取 `profile` 交给服务层——注意 `AvatarForm` 刻意不是 `ModelForm`，
   正是为了不在校验阶段就把新文件写进实例。
2. 服务层先读旧文件名与旧存储，再在事务里 `profile.avatar = new` +
   `save(update_fields=["avatar", "updated_at"])`（`FileDigestMixin` 会把 `sha256`
   补进 `update_fields`）+ 写 `accounts.avatar.update` 审计。
3. **提交之后**才删磁盘上的旧文件。

**批量加图**（`services.add_gallery_images`）
1. 事务内 `User.objects.select_for_update().get(pk=profile.user_id)`——锁加在**账号**行，
   因为配额是每人一份；不加锁时同一人开两个标签页会双双读到还没涨上去的用量。
2. 聚合出当前合计用量与 `Max(sort_order)`，然后逐张：`validate_gallery_image` 不过 → `rejected`；
   合计会超 → `overflowed`；其余落盘、`save()`、写一条 `accounts.gallery.add` 审计、用量累加。
3. 任意一步抛异常 → 事务回滚 + `delete_stored_files` 清掉本次已落盘的文件。
4. 视图分三截说结果：成功几张、逐张点名的 `rejected`、合并成一条的 `overflowed`（带已用量）。

**用户组整份覆盖**（`services.set_group_members`）
1. 后台的「组内用户」是 `FilteredSelectMultiple` 穿梭框，提交的是这个组**应有**的全部成员。
2. 事务内先 `Group.objects.select_for_update()` 锁住组那一行（两个管理员同时保存时排成队），
   再与现状求差集，只 `add` / `remove` 真正变了的人。
3. 真变了才写 `accounts.group.membership.update` 审计（谁进、谁出）；没变不写库也不留痕。

**取件**（`file_views`）
1. `@login_required` + `@require_GET`（匿名 302 到登录页）。
2. `get_object_or_404` 取 `Profile` / `GalleryImage`；没有头像直接 404。
3. `serve_file` 按扩展名猜 MIME 发出；文件不在盘上转 404；`sha256` 参数不传，因此响应不带
   `Content-Digest` / `X-Checksum-SHA256`（那套是给项目书、批注版、归档版的）。

---

## 5. 错误处理与诊断

**领域异常只有一个**：`services.GalleryError`（「请选择要上传的图片」一类），视图翻成
`messages.error`。其余「参数不该是这个值」一律抛 `ValueError`——那是编程错误，视图在调用前
先自行判定并把页面上的非法输入转成 `Http404`。

**拒绝形态**（页面上的实际表现）：

| 情形 | 表现 |
|---|---|
| 未登录访问受保护页面／取件口 | 302 到 `accounts:login`（带 `next`） |
| 登录但 `must_change_password=True` 访问任何成员功能 | 302 回改密页（中间件，带 `next`） |
| 访问别人的图册图 | 404（先按 `profile=` 过滤，不泄漏存在性） |
| 只读资料页的目标账号已停用 | 404 |
| 未知 `direction` / `layout` | 404（`Http404(_("未知操作"))`） |
| 账号或 IP 被 axes 锁定 | 403，`accounts.axes.lockout_response` 的中文页；正确口令也不放行 |
| 对 POST-only 视图发 GET | 405 |
| 受保护文件在磁盘上缺失 | 404（`serve_file` 把 `FileNotFoundError` 转掉，不 500） |

**审计 action**（`core.audit.record_audit`，**发过的字符串不再改**）：

| action | 触发点 |
|---|---|
| `accounts.qualification.grant` / `accounts.qualification.revoke` | `services.set_qualification`（只记这次真正动了谁） |
| `accounts.group.membership.update` | `services.set_group_members` |
| `accounts.avatar.update` / `accounts.avatar.clear` | 换／删头像 |
| `accounts.gallery.add` / `accounts.gallery.delete` | 每张成功入库／删掉的图各一条（与逐张对称） |
| `accounts.gallery.reorder` / `accounts.gallery.layout` | 调顺序／改排布 |
| `accounts.profile.update` | 资料表单保存（`detail` 记 `changed_data`） |
| `accounts.password.change` | 改密成功（含 `forced_flow`） |
| `accounts.login.lockout` | axes 锁定时（只记用户名，口令从不落库） |
| `accounts.user.create` / `accounts.user.update` | 后台用户编辑页保存 |

**日志**：`logging.getLogger(__name__)`，settings 里 `accounts` 这个 logger 是 DEBUG 级。
关键事件名：`auth.login.success` / `auth.login.failure` / `auth.login.redirect` /
`auth.login.lockout`、`auth.password_change.success` / `.failure`、
`profile.created` / `profile.skip` / `profile.repaired` / `profile.update.*` /
`profile.avatar.*` / `profile.gallery.add` / `profile.gallery.delete`、
`password_change.allow` / `password_change.redirect`。都带 `extra={"request_id": ...}`。
**日志与审计都不记口令**（`signals.log_user_login_failed` 与 `axes.lockout_response` 各有注释钉着）。

**刻意不报错**：重复保存同一份组员名单、重复授予已持有的资格 → 静默 no-op；
已在头／尾的移动、删一个本来没有的头像 → 返回 `False`，页面给一句 warning；
历史账号缺 `Profile` → 当场补一份并记 `profile.repaired`（不是错误）；
`FileDigestMixin` 算指纹时文件不在盘上 → 记 `file_digest.missing` warning，保存照常进行。

---

## 6. 测试要点与已知限制

### 测试

| 文件 | 钉住什么 |
|---|---|
| `tests/factories.py` | 跨模块共用件：两个临时媒体根（`TEST_MEDIA_ROOT` 与 `TEST_PRIVATE_MEDIA_ROOT` **平级、不嵌套**，分离本身是被测性质）、真图与真超限图 |
| `test_models_and_auth.py` | 建号即得 `Profile` 与 `must_change_password=True`；`create_superuser` 不受强制改密；无公开注册路由；首次改密解锁成员区；后续改密要旧密码；`next` 拒绝外站；失败日志与审计不含口令 |
| `test_admin_provisioning.py` | 后台建号带姓名与强制改密；**重置密码重新打开强制改密周期**；姓名只有 `full_name` 一个字段；成员进不了后台 |
| `test_login_lockout.py` | 账号与 IP 两个桶各算各的；锁定后正确口令也拒；403 中文文案；成功登录不清 IP 计数；审计不含口令 |
| `test_profile_pages.py` | 表单排布由 `ProfileForm.field_rows` / `narrow_fields` 声明；bio 上限；只读页的字段白名单（**不含学号与邮箱**）；非 GET 405；「我的获奖」入口带姓名跳转 |
| `test_avatar.py` | 2 MB 与非图片被拒；换头像删旧文件并刷新 `sha256`；删头像清字段与文件；取件要登录 + POST |
| `test_gallery.py` | 一批里逐张去留、点名报出；合计上限；中途失败回滚并清掉已落盘文件；顺序／排布／删除；别人的图 404；未知参数 404；登录 + POST |
| `test_protected_uploads.py` | 头像与图册落在受保护根、落盘名不含用户信息、存储不给 URL；登录可取、匿名 302；无头像 404 而不是 500 |
| `test_identity_panels.py` | 身份清单只列实际持有的、按目录顺序、对象身份带组名、空条目不出现；末条「用户组」；`describe_member` 五类；平台概览只给管理员与联系人 |
| `test_role_roster.py` | 名册只列持有者；六个批量动作授予／撤销；**没有批量授予管理员**；只读观察者提交不了动作；服务层拒绝白名单外的 flag |
| `test_group_membership.py` | 穿梭框可增删、可清空、可建组时带人；重复保存不变；改名不动名单；锁保证后一次保存读到前一次的结果 |

### 已知限制 / 当前不支持

- **本 app 不产出任何权限判定**（没有 `permissions.py`）。不变量靠「判定去问对应模块」维持；
  在 `accounts` 里新写「谁能做什么」的判断，就等于开了第二处真相。
- **图册合计上限只在服务层把关**：模型与数据库都没有跨行约束。绕过
  `services.add_gallery_images` 直接创建 `GalleryImage`（测试就是这么做夹具的）可以超限。
- **图册顺序的调整没有行锁**：`move_gallery_image` 只有事务、不锁账号行，同一账号两个标签页
  同时上移／下移时，后提交者按自己读到的顺序整段重排，可能覆盖前一次调整。
  配额那条路有锁，顺序这条路没有。
- **批量资格的写没有行锁**（与 `add_gallery_images` 的账号行锁不同）：设计上以最后提交的为准，
  **没有并发用例**。
- **头像与图册的 `sha256` 存库但不随响应发**：`file_views` 不传该参数，所以图片类没有
  `Content-Digest` / `X-Checksum-SHA256`——这是刻意的（图片不在页面上展示校验值）。
- **本人改不了自己的 `username` 与 `email`**：`ProfileForm` 不在其列，改这些要进后台。
- **`must_change_password=True` 连 `/admin/` 也进不去**：中间件的白名单只有改密页与登出页。
  给一个还带着初始密码的账号勾 `is_staff`，它在改密之前打不开后台。
- **删账号会被审计的只追加触发器挡下**：账号自己名下有审计行时，删他要先把那些行的
  `user` 置空（外键是 `SET_NULL`），而那是一次 `UPDATE` —— 数据库直接拒绝，后台点删除会以
  `DatabaseError` 收场（一条审计行都没有的账号照常删得掉）。**账号退场的口径是停用**
  （后台取消 `is_active`，见 §3 的 `is_active` 一行），真要删见 [`docs/deploy.md`](../docs/deploy.md) §5.3 的逃生口。
- **`first_name` / `last_name` 仍在表上**：不再出现在任何界面与表单，历史数据由迁移
  `0004_copy_legacy_names` 合并进 `Profile.full_name`；不要把这两个字段重新接进业务。
- **只读资料页的公开口径**：`college` / `major` / `specialty` / `bio` / `phone` / `contact`
  对任何登录成员可见，`student_id` 与 `email` 不显示；页面上没有任何表单。
