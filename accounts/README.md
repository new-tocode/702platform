# accounts 模块

> 账号与成员身份：自定义 `User`（`AUTH_USER_MODEL`）、`Profile`、个人图册、强制改密流程、
> 头像与图册的受保护取件，以及后台的四张全局身份名册。
> **它不判「谁能做什么」**（本 app 没有 `permissions.py`），也不管项目组与评审的业务规则——
> 资格、联系人、组员各自的判定都在别的 app。
> 它是依赖图的根：所有业务 app 的用户外键都指向它。

**什么时候看**：改账号字段、改登录／改密流程、动个人信息页、碰头像与图册、
改资格的批量授予入口，或者要给 `User` 加一个布尔字段时。

---

## 1. 明确不做什么

| 不在这里 | 落在哪 |
|---|---|
| 「谁能做什么」的判定 | **本 app 没有 `permissions.py`**：管理员问 `core.permissions.is_admin`，项目组联系人／成员问 `projects.permissions`，评审资格问 `reviews.permissions` |
| 评审资格怎么用（抽人、门槛、待办） | `reviews`；`accounts` 只存三个资格字段，并提供后台批量写入口 |
| 接单开关的**规则**（能不能关、关了谁被排除） | `reviews`：字段住在 `User`（`receives_preliminary_tasks` / `receives_review_tasks`），但写入口只有 `reviews.services.set_reviewer_availability`（后台动作在 `accounts/admin.py`，函数体内 import） |
| 强制改密的**拦截** | `config.middleware.ForcePasswordChangeMiddleware`；`accounts` 只提供改密页和这个字段 |
| 登录失败计数、锁定判定、冷却时长 | django-axes + `config/settings.py` 的 `AXES_*`；`accounts.axes` 只把锁定响应换成站内中文页并写审计 |
| 项目书、批注版、归档版、帖子图的取件 | `projects` / `reviews` / `discussion`；`accounts.file_views` 只管头像与图册 |
| 上传校验实现、存储、取件响应、文件指纹 | `core.uploads` / `core.storage` / `core.downloads` / `core.hashing` |
| 内部通知的投递语义 | `notices`；`auth.Group` 的成员关系在这里维护，只当通知的收件范围，**不是身份** |
| 公开注册、自助找回密码 | 有意不做；忘密码由管理员在后台重置 |

## 2. 必须成立的断言

- **上限分两层**：单张在 `validators.py` 的常量，整册合计在 `models.GALLERY_TOTAL_MAX_BYTES`。
  合计要跨行求和，模型与数据库都没有这条约束，**唯一的执行点是 `accounts.services.add_gallery_images`**；
  绕过它直接建 `GalleryImage` 可以超限。
- **身份的唯一真相源是 `User` 上的布尔字段**：四张名册是 proxy，不建表、不存第二处数据，
  所以不存在「名册与字段分叉」这种状态。
- **每个账号必有一份 `Profile`**：`post_save` 信号在 `created` 时补（`raw` 加载夹具时跳过）；
  建号早于该信号的历史账号由 `views._member_profile` 的 `get_or_create` 当场补齐并记日志。
- **头像与图册一律走受保护根**：模板取图走 `{% url 'accounts:avatar_file' %}` / `gallery_file`。
  这不是风格问题——`PrivateStorage.url()` 返回空串，写 `{{ field.url }}` 只会得到空地址。
- **审计与文件系统不在事务里，事务边界不统一**（改之前先看清是哪一种，别按「一律」记）：
  `set_avatar`、`clear_avatar`、`gallery.add`、`gallery.delete` 的审计行与数据写在**同一个 `atomic` 里**；
  而 `set_qualification` 与 `set_group_members` 的**审计在事务提交之后写**（数据先落、审计后写——
  两步之间进程挂掉会留下「资格改了但审计里没有」，这是既有行为，与 `projects`／`reviews` 的口径一致）。
  `move_gallery_image` 只有重排在事务里、`set_gallery_layout` 完全不开事务。
  **文件删除一律放在提交之后**（失败顶多多留一个旧文件，不会出现「库里还指着、盘上没了」）；
  批量加图相反，中途失败要清掉这次已经落盘的新文件。

## 3. 已知限制 / 当前不支持

- **本 app 不产出任何权限判定**（没有 `permissions.py`）。在 `accounts` 里新写「谁能做什么」的判断，
  就等于开了第二处真相。
- **`set_avatar` / `clear_avatar` 要求传进数据库里取出来的那份 `profile`**：传被表单改过的实例时，
  `profile.avatar.name` 读到的已经是新图，旧文件会因为「删新文件」而留下。
- **图册合计上限只在服务层把关**：模型与数据库都没有跨行约束。绕过
  `services.add_gallery_images` 直接创建 `GalleryImage`（测试就是这么做夹具的）可以超限。
- **图册顺序的调整没有行锁**：`move_gallery_image` 只有事务、不锁账号行，同一账号两个标签页
  同时上移／下移时，后提交者按自己读到的顺序整段重排，可能覆盖前一次调整。
  配额那条路有锁，顺序这条路没有。
- **资格批量动作的 HTTP 门槛只在 `@admin.action(permissions=["change"])` 这一行上**：
  漏声明，只挂 `view_user` 的只读观察者也能提交（服务层只认 flag 白名单，管不住 HTTP 门槛）。
- **批量资格的写没有行锁**（与 `add_gallery_images` 的账号行锁不同）：设计上以最后提交的为准，
  **没有并发用例**。`set_group_members` 的两条 `Group.objects.select_for_update()` 也只把并发保存串行化，
  用例是两次串行调用，真并发没有用例。
- **头像与图册的 `sha256` 存库但不随响应发**：`file_views` 不传该参数，所以图片类没有
  `Content-Digest` / `X-Checksum-SHA256`——这是刻意的（图片不在页面上展示校验值）。
- **本人改不了自己的 `username` 与 `email`**：`ProfileForm` 不在其列，改这些要进后台。
- **`must_change_password=True` 连 `/admin/` 也进不去**：中间件的白名单只有改密页与登出页。
  给一个还带着初始密码的账号勾 `is_staff`，它在改密之前打不开后台。
- **删账号会被审计的只追加触发器挡下**：账号自己名下有审计行时，删他要先把那些行的
  `user` 置空（外键是 `SET_NULL`），而那是一次 `UPDATE` —— 数据库直接拒绝。后台点删除的
  结果是 **500**（抛的是 `ProgrammingError` 而不是 `IntegrityError`，admin 里接
  `ProtectedError` / `RestrictedError` 的分支接不住它，页面不会给出人话）；一条审计行都
  没有的账号照常删得掉。**账号退场的口径是停用**
  （后台取消 `is_active`），真要删见 [`../docs/更新维护/开发与部署.md`](../docs/更新维护/开发与部署.md) §6 的逃生口。
- **`first_name` / `last_name` 仍在表上**：不再出现在任何界面与表单，历史数据由迁移
  `0004_copy_legacy_names` 合并进 `Profile.full_name`；**不要把这两个字段重新接进业务**。
- **只读资料页的公开口径**：`college` / `major` / `specialty` / `bio` / `phone` / `contact`
  对任何登录成员可见，`student_id` 与 `email` 不显示。页面上没有任何**资料**表单；今天唯一能提交的
  是页头「私信」那个小浮动窗（写私信这件事整个归 `notices`）。

## 4. 由来

- **`first_name` / `last_name` 为什么还在表上**：`User` 继承 `AbstractUser` 带来的历史列，
  界面与业务都改用 `Profile.full_name`，历史数据由迁移 `0004_copy_legacy_names` 合并过去。
  留着是因为删列要动 `AbstractUser` 的既有契约，收益不抵风险——但**别再把它接回业务**。
