# discussion 模块

> 社团空间：板块、帖子（配图、置顶）、软删除的评论、成员目录，以及正文里 `@姓名` 的解析。
> **它不拥有消息**——提及消息的写入与撤回归 `notices`；不存身份与资格（`must_change_password`
> 在 `accounts`，本 app 只读它）；不判「谁算管理员」（问 `core.permissions.is_admin`）；
> 不做后台（**本 app 没有 `admin.py`**，Board／Post／Comment 都不进 Django Admin）。
> `content` 直接 import 它提供的成员判据，`notices` 依赖它的帖子／评论外键与「第几页」查询，
> 顶栏栏目注册也认它。

**什么时候看**：改板块／帖子／评论的规则或页面、动 `@` 提及、碰发言限速、改帖子图的取件口径，
或者要回答「谁能看到社团空间里的什么」的时候。

---

## 1. 职责与边界

**负责**（都在 `discussion/` 下）：

| 东西 | 代码坐标 |
|---|---|
| `Board`、`Post`、`PostImage`、`Comment`（含软删除字段与两个经理） | `models.py` |
| 空间页 `discussion:space` 与板块页 `discussion:board`：板块滑轨、帖子流、评论区、成员目录 | `views.py`、`selectors.py`、`templates/discussion/space.html` |
| 发帖／编辑／删帖／置顶，含每帖图片的增删与上限 | `views.py`、`forms.py`、`services.py`、`templates/discussion/post_form.html` |
| 评论发布与（软）删除 | `views.py`、`forms.py`、`services.py` |
| 板块的前台创建与删除 | `views.py`、`forms.py`、`services.py` |
| `@姓名` 的解析（只回答「这段文本提了谁」） | `mentions.py` |
| 发言限速：`SPEAKING_RATE_LIMIT` / `SPEAKING_RATE_WINDOW` | `services.py` |
| 只读查询：板块列表、板块帖子（预取评论与配图）、帖子页码、成员目录 | `selectors.py` |
| 板块名清洗、图片上限常量、`validate_post_image` | `validators.py` |
| 成员门槛与「谁能对这条帖子／评论做什么」的全部判定 | `permissions.py` |
| 帖子图的**唯一**取件口 `discussion:post_image` | `views.py`（经 `core.downloads.serve_file`） |
| 前台脚本：长帖折叠、`data-confirm` 确认、`@` 补全、板块滑轨定位 | `static/js/discussion.js`、`static/js/mentions.js` |
| 路由（挂在 `/member/space/` 下） | `urls.py`、`config/urls.py` |

**明确不做**——划出去的事，各自落在哪：

| 不在这里 | 落在哪 |
|---|---|
| 提及**消息**的写入与撤回 | `notices.services.sync_mention_messages` / `clear_mention_messages`——`Message` 归它所有；`Message.post` / `Message.comment` 用字符串外键指回来，加载期不依赖本 app |
| 成员身份、姓名、头像、账号是否被锁 | `accounts`：`is_member` 读的 `is_active` / `must_change_password` 都存在 `User` 上 |
| 「谁算管理员」 | `core.permissions.is_admin`；删帖、删评论、置顶都调它，不写 `user.is_staff` |
| 受保护件的存储、落盘命名与取件响应 | `core.storage`（`private_storage`、`neutral_upload_to`）、`core.downloads.serve_file` |
| 图片的扩展名／大小／MIME／真实签名校验 | `core.uploads.validate_image_upload`；本 app 的 `validators.validate_post_image` 只给上限与文案 |
| 帖子正文的 Markdown 渲染与 HTML 白名单 | `content.templatetags.rendering.render_markdown`（模板里用） |
| 成员只读资料页 | `accounts:member_profile`；成员目录只负责链过去 |
| 操作入口注册 | 本 app 不注册任何 `core.registry` 条目（`apps.py` 只有 `verbose_name = "社团空间"`，没有 `ready()`） |

**上游依赖**：`django.contrib.auth`、`django.contrib.messages`、`core.permissions`、`core.audit`、
`core.storage`、`core.downloads`、`core.hashing`、`core.forms`（多文件字段件）。
跨 app import 一律在函数体内（`notices.services`），加载期不牵连它。

**下游消费者**：

- `content.permissions.can_manage_awards` **加载期** `from discussion.permissions import is_member`——
  本 app 的成员判据是跨 app 共用的那一份。
- `notices`：`notices/models.py` 以字符串外键指向 `discussion.Post` / `discussion.Comment`（帖子或评论
  删掉时级联删消息）；`notices.selectors._mention_content` 在函数体内 import `discussion.selectors.page_of_post`，
  拼出「板块页 + `?page=N` + `#post-N`／`#comment-N`」的消息链接。
- `core.context_processors.NAV_BY_VIEW` 把本 app 的视图名映射到顶栏「社团空间」，`MEMBER_NAMESPACES`
  含 `discussion`；`templates/discussion/` 里的两个模板延伸自 `base.html`。

---

## 2. 关键接口与失败模式

服务层（写操作自带事务），领域异常一律是 `DiscussionError` 家族：

| 入口 | 语义 | 前置条件 | 失败模式 |
|---|---|---|---|
| `services.create_post` | 发帖：锁板块行、写帖、存图、同步提及 | `can_create_post`（成员）；未触发限速；标题与正文 strip 后非空；图片 ≤ `POST_IMAGE_LIMIT` 张且逐张通过 `validate_post_image` | `PermissionDenied`；`DiscussionError`（限速、空标题／正文、图片超过 3 张或单张超过 3 MB，文案直接给用户看）；`DiscussionNotFound`（板块没了）；任意异常 → 回滚 + `delete_stored_files` 清掉本次已落盘的新图 |
| `services.update_post` | 改帖并按 `remove_image_ids` 增删配图，重算提及 | 锁内再判 `can_edit_post`（作者本人）；`remove_image_ids` 是整数；这些 id **必须整份属于这篇帖子**；剩余 + 新增 ≤ 3 | `DiscussionError`（「所选图片无效。」／「所选图片不属于这篇帖子。」／「每篇帖子最多保留 3 张图片。」）；`PermissionDenied`；`DiscussionNotFound` |
| `services.delete_post` | **硬删**帖子：评论行与图片行级联走，磁盘上的图片文件在提交后删 | `can_delete_post`（作者或 `is_admin`） | `PermissionDenied`；`DiscussionNotFound`；审计里先记 `comment_count` / `image_count` 再删，删完返回 `board_id` 供视图跳转 |
| `services.set_post_pinned` | 置顶／取消置顶 | `can_pin_post`（成员且 `is_admin`） | `PermissionDenied`；`is_pinned` 只认 `"true"` / `"false"`，别的值视图先返回 400（不落到服务层） |
| `services.create_comment` | 评论 + 该评论上的提及 | `can_comment`（成员）；未触发限速；内容非空 | `PermissionDenied`；`DiscussionError`；`DiscussionNotFound`（帖子没了） |
| `services.delete_comment` | **软删**评论 + 撤回它的提及消息 | `can_delete_comment`（作者或 `is_admin`） | `PermissionDenied`；`DiscussionNotFound`；**已经删过 → 幂等短路**，不改首次的删除人与删除时间，也不重复写审计 |
| `services.create_board` | 建板块 | `can_create_board`（`is_superuser`）；中英名各自过清洗 | `PermissionDenied`；`DiscussionError`（名字为空／不合规）；`BoardNameTaken`（撞唯一约束） |
| `services.delete_board` | 删空板块 | `can_delete_board`（同上）；锁内确认板块**没有帖子** | `PermissionDenied`；`BoardNotEmpty`（「请先删除板块中的所有帖子…」）；`DiscussionNotFound` |
| `selectors.posts_for_board` | 板块帖子流，预取评论（只取未删的）与配图、作者资料 | 只读，不写库 | 不抛；排序即 `Post.Meta.ordering`（置顶优先、时间倒序） |
| `selectors.page_of_post` | 帖子的页码（1 起），消息链接靠它 | 只读；**顺序必须与 `posts_for_board` 一致** | 不抛领域异常；帖子不在这个板块（或已删）时 `list.index` 抛 `ValueError`——调用方目前都传存在的帖子 |
| `selectors.member_directory` | 活跃账号目录，可按姓名过滤 | 只读 | 不抛；只过滤 `is_active`，`must_change_password` 的账号也在内 |
| `mentions.extract_mentions` | 从文本里解析被提到的人（按出现顺序去重） | 只读；只认 `Profile.full_name` | 不抛；没有任何人有姓名时返回 `[]` |
| `views.post_image` | 帖子图的唯一出口，经 `serve_file` 发出 | `@login_required` + 成员门槛 | 匿名 302 到登录页；非成员 403；图片记录不存在 404；文件不在盘上 404（`serve_file` 把 `FileNotFoundError` 转掉）；**不发指纹响应头**（不传 `sha256`） |
| `views.*`（除上述取件口） | 页面与写入口 | 全部 `@login_required`；写入口 `@require_POST`，读页面 `@require_GET` | 首次改密中的账号被中间件 302 回改密页；非成员 403；GET 打 POST 入口 405；非法 `is_pinned` 400 |

---

## 3. 状态与不变量

### Board

| 字段 | 决定什么 |
|---|---|
| `name_zh` / `name` | 中英双语名，都 ≤80。`name` 只收 ASCII 与常见标点（`validators._BOARD_NAME`），`name_zh` 必须含中文（`_CHINESE_BOARD_NAME`）；两者都是**原样用户内容**，不进 `.po` |
| `name` 的唯一约束 | `UniqueConstraint(Lower("name"), name="discussion_board_name_ci_uniq")`——**大小写不敏感**；`name_zh` 不唯一，中文可以重名 |
| `created_by` | `on_delete=PROTECT`；建板块的账号删不掉 |
| `Meta.ordering` | `("name_zh", "name", "pk")`，也就是滑轨与「默认选中第一个板块」的顺序 |

### Post

| 字段 | 决定什么 |
|---|---|
| `board` | `on_delete=PROTECT`：有帖子的板块删不掉（模型层这道保护与服务层的 `BoardNotEmpty` 是双保险） |
| `author` | `on_delete=PROTECT` |
| `title` / `content` | 200 / 20000。**清单只钉了 `Post.content` 与 `Comment.content`**（`core.tests.test_upload_validation` 的上限表），`title` 的 200 不在其中——改它不会触发兜底测试 |
| `is_pinned` | 排序第一关键字（`("-is_pinned", "-created_at", "-pk")`）；只有管理员能动 |
| 两条索引 | `discussion_post_feed_idx` 供列表；`discussion_post_rate_idx`（`author`, `created_at`）专供限速计数，不扫全表 |

### PostImage（`FileDigestMixin`，`digest_field = "image"`）

| 字段 | 决定什么 |
|---|---|
| `image` | `private_storage` + `neutral_upload_to("discussion")`：落在 `PRIVATE_MEDIA_ROOT` 下、名为 `discussion/YYYY/MM/<uuid>.<ext>`，单张 ≤ `POST_IMAGE_MAX_BYTES`（3 MB，`validate_post_image` 里配文案） |
| `file_size` | `save()` 时从 `image.size` 写入，`editable=False`；`save()` 每次还跑 `full_clean()` |
| `sha256` | 保存时由 `FileDigestMixin` 维护；**存库但从不随响应发**（见 §5） |

### Comment

| 字段 | 决定什么 |
|---|---|
| `content` | 4000 |
| `deleted_at` / `deleted_by` | 软删除的两个字段；`deleted_by` 是 `SET_NULL`，删账号不会带走评论行 |
| `objects`（默认经理） | `CommentManager` **只给未删除的**；`Meta.default_manager_name = "objects"` 让反向关系 `post.comments` 也走它 |
| `all_objects` | 未过滤的 `CommentQuerySet`；限速计数与「已删评论仍能再删一次」走这条 |
| `soft_delete(actor=...)` | 幂等：已删的不覆盖原删除人与时间 |

### 必须成立的断言

- **成员的门槛只有 `discussion.permissions.is_member` 一个判据**：登录 + `is_active` + 不是
  `must_change_password`。`content.permissions.can_manage_awards` 直接 import 它——改这里的口径，
  历年获奖页的可写范围会跟着变。
- **建／删板块只认 `is_superuser`**（`can_create_board`），不是 `is_admin`：一位 `is_staff` 但非
  superuser 的管理员在板块页看不到管理控件。这是全平台唯一把 `is_superuser` 当独立资格用的地方。
- **硬删的是帖子，软删的是评论**：删帖连带评论行、图片行与磁盘文件；删评论只写 `deleted_at` /
  `deleted_by`，行与内容都留着（一条有人回过的评论硬删掉，「删过」这件事就无从追查）。删帖时软删过的
  评论照样跟着走——Django 收集待删对象用的是不过滤的 `_base_manager`。
- **发言限速是发帖 + 评论共用的一个桶**：`SPEAKING_RATE_LIMIT = 45` 条 / `SPEAKING_RATE_WINDOW = 60` 秒，
  计数走 `Post.objects` + `Comment.all_objects`——**已软删的评论也算**，否则「发满、删掉、再发」是免费口子。
  挡的主要不是帖子本身，而是 `@` 提及：它给任意成员写站内消息，是站内唯一能主动投递内容的通道。
- **每帖 ≤ `POST_IMAGE_LIMIT = 3` 张、单张 ≤ `POST_IMAGE_MAX_BYTES = 3 MB`**，上限在**表单与服务层各判一次**
  （表单先给友好报错，服务层兜住绕过表单的调用），两处读的是 `validators` 里同一份常量。
- **帖子图是受保护件**：`PRIVATE_MEDIA_ROOT` 刻意不在 `MEDIA_ROOT` 之下，Nginx 的 `/media/` 指不到；
  落盘名是 uuid（原文件名会带人名）。页面一律 `{% url 'discussion:post_image' image.pk %}`，
  **不写 `{{ field.url }}`**（`PrivateStorage.url()` 返回空串，写上去只会得到空地址）。
- **板块名的唯一真相源是数据库约束**：`BoardForm.clean_name` 只是先把冲突翻成一句中文，
  服务层再把 `IntegrityError` 翻成 `BoardNameTaken`。绕开两者直接 `Board.objects.create` 仍会被约束挡下。
- **`@` 提及的权威在服务端**：正文里写了 `@姓名` 就算提及，前端补全（`mentions.js`）只是帮忙打字；
  「这段文本提了谁」的唯一实现是 `mentions.extract_mentions`。
- **提及消息按 diff 对齐，不是只增不减**：`notices.services.sync_mention_messages` 以
  `(kind=mention, post, comment)` 为界对齐——编辑后新增的写消息、去掉的删消息；自己 `@` 自己不发。
- **长帖折叠只有 CSS 一个出处**：`.discussion-post-content.is-collapsed` 的 `max-height`
  （`static/css/app.css`）是「多长算长」的唯一定义，`discussion.js` 不重复这个数字，模板里也**不写**
  `is-collapsed`（没有脚本时正文整段照常显示，按钮默认带 `hidden`）。

---

## 4. 数据流与时序

**发帖**（`services.create_post`）

1. `can_create_post` → `_enforce_speaking_rate`（按当前时间往前 60 秒计数）→ strip 标题正文 →
   `_validated_images`（先数张数、再逐张 `validate_post_image`）。
2. 事务内：`_board_for_update` 锁板块行 → 建 `Post` → `_store_post_images` 逐张落盘并记下
   `(storage, name)` → `_sync_mentions`（`comment=None`，即帖子正文上的提及）。
3. 任何一步抛异常 → `delete_stored_files(saved_files)` 清掉本次已落盘的新图再往上抛；
   单张图落盘失败时 `_store_post_images` 自己先把那半张删掉。
4. 提交之后写 `discussion.post.create` 审计（`detail` 记 `board_id` 与 `image_count`），视图
   `messages.success` 后跳回板块页。

**编辑帖子**（`services.update_post`）

1. 锁的是**帖子行**（`_post_for_update`），再 `select_for_update` 锁这一帖现有的图——两个标签页同时
   加图不会把总数顶过 3。
2. `remove_ids` 必须整份落在现有图里；要删的图先记 `(storage, name)`、删行，**文件等事务提交后再删**；
   新图在同一事务里落盘。
3. 编辑后 `@` 的人可能变了，重跑 `_sync_mentions` 做 diff：新出现的写消息、被去掉的删消息。

**评论**（`services.create_comment` / `delete_comment`）

1. 发评论：限速 → 锁帖子行 → 建 `Comment` → `_sync_mentions(comment=comment)`——评论上的提及以这条
   评论为界，与帖子正文上的互不影响。
2. 删评论：锁 `Comment.all_objects`（**已删的也锁得到**，重复提交因此是空操作而不是 404）→
   `can_delete_comment` → 已经删过就直接返回 → `soft_delete` → `clear_mention_messages(comment=...)`
   撤回别人的消息（局部 import）→ 写 `discussion.comment.delete` 审计。评论没有文件，全程不碰磁盘。

**删帖**（`services.delete_post`）

1. 事务内锁帖子行、判权限，把图片清单与 `comment_count` / `image_count` 先写进审计 `detail`，
   再 `post.delete()`——评论行、图片行随之级联消失。
2. **提交之后**才按清单删磁盘上的图片文件（失败顶多多留几个孤儿文件，不会出现「库里还指着、盘上没了」）。
3. 帖子上的提及消息不在这里显式撤回：`Message.post` 的级联外键负责。

**删板块**（`services.delete_board`）

1. 锁板块行 → `board.posts.exists()` 为真则 `BoardNotEmpty` → 写审计 → `board.delete()`。
2. 模型层 `Post.board` 的 `PROTECT` 是第二道；发帖同样锁板块行，避免「新帖写入」与「删除板块」交错
   绕过空板块条件。

**并发锁一览**

| 操作 | 锁 | 挡什么 |
|---|---|---|
| 发帖 / 删板块 | `Board` 行（`select_for_update`） | 新帖与删板块交错 |
| 编辑帖子 | `Post` 行 + 该帖 `PostImage` 行 | 两个标签页同时加图超出 3 张 |
| 发评论 / 删帖 | `Post` 行 | 帖子被删掉后还往上挂评论 |
| 删评论 | `Comment` 行（含已删的） | 重复提交覆盖首次的删除人与时间 |
| 发言限速 | **不加锁**（刻意） | 见 §6：多出一两条不值得给每条发言串行化 |

---

## 5. 错误处理与诊断

**领域异常**：基类 `DiscussionError`，三个子类各有分工——`DiscussionNotFound` 翻成 HTTP 404；
`BoardNameTaken` / `BoardNotEmpty` 带用户文案，视图 `messages.error` 后跳回原页。
「参数不该是这个值」不是异常：视图先判，`post_pin` 收到 `is_pinned ∉ {"true","false"}` 直接 400。

**拒绝形态**（页面上的实际表现）：

| 情形 | 表现 |
|---|---|
| 未登录访问任何 discussion 视图 | 302 到 `accounts:login`（带 `next`） |
| 登录但 `must_change_password=True` | 302 回改密页——比视图更早，是 `config.middleware.ForcePasswordChangeMiddleware` 挡的 |
| 已登录但未通过 `is_member` | 403（`core.permissions.require` 抛 `PermissionDenied`）——**页面上基本到不了这一支**：`is_active=False` 的账号会被 Django 判成匿名（302），首次改密未完成的被中间件先拦（302）。它实际是服务层与测试可达的防御性判定 |
| 编辑别人的帖子 | 403（视图先记 `discussion.post.edit.denied` 再抛） |
| 删别人的帖子／评论，或非管理员置顶任何帖子 | 403 + 对应的 `.denied` 日志 |
| 非超级管理员建／删板块 | 403 |
| 板块、帖子、评论、图片不存在 | 404 |
| `is_pinned` 传了别的值 | 400 |
| 对 POST-only 入口发 GET | 405 |
| 盘上缺了帖子图 | 404（`serve_file` 转掉 `FileNotFoundError`，不是 500） |

**审计 action**（`core.audit.record_audit`，**发过的字符串不再改**）：

| action | 触发点 |
|---|---|
| `discussion.board.create` / `discussion.board.delete` | 建／删板块（`detail` 记双语名） |
| `discussion.post.create` | 发帖（`detail` 记 `board_id`、`image_count`） |
| `discussion.post.update` | 编辑帖子（另记 `removed_image_count`） |
| `discussion.post.delete` | 删帖（`detail` 记作者、评论数、图片数——行删了以后这些只在这里查得到） |
| `discussion.post.pin` / `discussion.post.unpin` | 置顶／取消置顶 |
| `discussion.comment.create` / `discussion.comment.delete` | 发评论／软删评论（删除记 `is_author`） |

**审计的事务边界不统一**：`delete_board`、`delete_post`、`delete_comment` 的审计写在**事务内**；
`create_board`、`create_post`、`update_post`、`set_post_pinned`、`create_comment` 写在**事务提交之后**。
后半类若审计写失败，数据已经落库而没有留痕——这是现状，不是设计声明，改动时别当它是有意为之。

**日志**：视图层用 `logging.getLogger(__name__)`（`discussion.views`），事件名
`discussion.post.edit.denied` / `discussion.post.delete.denied` / `discussion.comment.delete.denied`；
门槛拒绝走 `core.permissions.require`，事件名由调用方给：`discussion.permission.denied`、
`discussion.board.create.denied`、`discussion.board.delete.denied`、`discussion.post.pin.denied`。
都带 `extra={"request_id": ...}`。settings 的 `LOGGING` 里有 `discussion` 这一节（DEBUG 级 +
`console`/`file` 两个 handler），与其余自家 app 一致，都落 `logs/django.log`；
`core.permissions` 那几条另有 `core` 这一档兜住。

**刻意不报错**：重复删除同一条评论 → 幂等短路，页面照常跳转、不写第二次审计；限速的拒绝条件是
「窗口内已有 ≥ `SPEAKING_RATE_LIMIT` 条」，也就是每分钟发得出 45 条、第 46 条才被拒；
编辑帖子把某个 `@` 去掉 → 那条消息被静默撤回，不发任何提示。

---

## 6. 测试要点与已知限制

### 测试

| 文件 | 钉住什么 |
|---|---|
| `tests/base.py` | 视图测试的共同夹具：四个账号（成员／另一成员／staff／超级管理员）+ 一个板块，`must_change_password` 显式关掉。共用是因为这套夹具**不决定任何随机结果**（讨论区没有抽签）——与 `reviews/tests` 刻意不共用夹具的情形相反 |
| `tests/factories.py` | 两个临时媒体根（`TEST_MEDIA_ROOT` 与 `TEST_PRIVATE_MEDIA_ROOT` **平级、不嵌套**，分离本身是被测性质）与一张真 PNG 上传件 |
| `test_space_access.py` | 匿名 302、首次改密账号被送去改密页；顶栏入口只对成员出现且在讨论页高亮；成员看得到空间与板块、看不到管理控件；成员目录按姓名过滤并链到只读资料页 |
| `test_boards.py` | 前端建／删板块只认超级管理员；非空板块删不掉；未知 id 404 |
| `test_posts.py` | 作者取自登录账号、编辑仅作者本人；HTTP 上传图片与编辑移除一张；帖子图只发给成员；删帖 POST-only 且管理员可删任意帖；非法置顶参数 400；模板只留折叠钩子、**绝不预置 `is-collapsed`** |
| `test_comments.py` | 删除按钮只对作者与管理员渲染；删除 POST-only、判定在服务层；已删评论从页面与计数里消失、帖子与其余评论不受影响；未知评论 404、被锁账号被挡 |
| `test_images.py` | 三张合法图可发、删帖清文件；每张图各记一份 `sha256`；第四张与超 3 MB 被拒；编辑增删后仍 ≤3；表单层同样卡数量 |
| `test_mentions.py` | 解析：`@` 后接姓名、账号名不算、邮箱里的 `@` 不算、最长匹配优先、重复合并、同名发给所有同名者；消息：发帖／评论各写一条、重复提及只一条、自己 `@` 自己不发、编辑按 diff 增删、软删评论撤回、删帖连带删除、消息链接带页码与锚点 |
| `test_models.py` | 板块名大小写不敏感唯一；空板块可删、有帖不可删；排序置顶优先、其余时间倒序；删帖级联删评论；默认经理挡掉软删评论 |
| `test_services.py` | 服务层的作者／管理员／超级管理员分层；建帖与删板块锁板块行；评论软删幂等且保留首次删除人；删帖带走软删评论；停用／锁定／匿名账号用不了服务；同名板块翻成领域异常 |
| `test_forms.py` | 板块表单要中英双名且英文名合规；帖子与评论表单拒空白内容 |
| `test_selectors.py` | 成员目录按姓名过滤并排除停用账号；帖子选择器预取评论与作者资料 |
| `test_rate_limit.py` | 阈值从 `services` 常量读（不写死数字）；帖与评论共用一个桶；**已软删的评论仍计数**；别人不受影响 |

### 已知限制 / 当前不支持

- **发言限速不严格**：检查与写入之间没有锁，两个并发请求可能同时通过，多出一两条。这是刻意的选择
  （限速挡的是脚本化刷屏，为此给每条发言串行化得不偿失）；真正要求严格不超的地方（库存、评审席位）
  另有行锁。**限速与「已删评论仍计数」同源**：删掉自己的话不会把配额还回来。
- **软删评论在页面上直接消失，没有占位行**：模板遍历的是默认经理（只含未删的），所以内容、计数与
  `#comment-N` 锚点一起没了。提及消息已由 `clear_mention_messages` 撤回，正常路径下不会有人点进来；
  但 `models.Comment` 的注释与 `notices.services.clear_mention_messages` 的 docstring 里写的
  「在界面上让位给一行说明」「点过去只会看到该评论已删除」**按模板现状并不成立**：页面既没有占位行，
  也没有那句话。以模板与测试为准，改文案时别照抄这两处注释。
- **`page_of_post` 要数一遍板块的全部帖子 id**（取全量 `pk` 再 `.index()`）：板块帖子多时是 O(n) 的内存与
  时间。它是「第几页」的唯一实现，`notices` 的消息链接依赖它；**改 `posts_for_board` 的排序时必须同步改它**，
  否则消息会落到别的页。
- **本 app 没有后台页面**（无 `admin.py`）：板块改名、删除有帖的板块都只能走前台（先清空帖子）或直接改库。
- **板块名的大小写不敏感唯一只作用于 `name`**：`name_zh` 没有唯一约束，中文可以重名。
- **超级管理员的判定有两处写法**：`permissions.can_create_board` / `can_delete_board` 与服务层是权威，
  而模板上的管理控件由 `views._space_context` 的 `can_manage_boards = request.user.is_superuser` 控制。
  改判定时要一起改，否则会出现「按钮在、提交 403」或「按钮没了、接口还开着」。
- **成员目录与 `@` 补全名单都包含「首改密中」的账号**：两者只过滤 `is_active`。这是有意的（他们改完密码
  就能看帖，消息放着不碍事），不要在别处再补一次 `must_change_password` 过滤，否则三处口径分叉。
- **同名会发给所有同名账号**：`mentions.name_map` 把姓名映射到用户列表，`extract_mentions` 对同名的每个人
  都算一次提及；`mentions.js` 的补全同样只按姓名匹配。
- **帖子图的 `sha256` 存库但不随响应发**：`views.post_image` 不传 `sha256`，图片类刻意没有
  `Content-Digest` / `X-Checksum-SHA256`（那套是给项目书、批注版、归档版的）。
- **正文渲染的安全边界不在本 app**：帖子正文经 `content.templatetags.rendering.render_markdown` 处理
  （去 `script` / `style` + bleach 白名单），评论只做 `linebreaksbr`。允许哪些标签由 `content` 决定。
- **帖子图的文件名与日期目录由 `core.storage` 决定**：`validators.post_image_upload_to` 是**已被换掉**的旧口径
  （迁移 `0004` 引它，`0006` 换成 `core.storage.NeutralUploadTo("discussion")`），只留给历史迁移引用，
  **新上传不走它**，不要把它接回模型。
