# notices 模块

> 站内通知与消息：管理员发布的**公告**（`Notice`，三种可见范围）、成员侧的「我的消息」页，
> 以及**事件型消息**（`Message`，一行一个收件人）。可见性收敛在 `visibility.py` 一处；
> 公告由后台发布，事件消息由别的 app 在自己的事务里调 `services.py` 写入。
> **它不判「谁能做什么」**（本 app 没有 `permissions.py`），不解析 @ 提及（归 `discussion.mentions`），
> 不管消息点开后那一页（帖子／项目组／评审队列各归其主），也不替别的 app 写事务与审计。
> `discussion`、`reviews`、`projects` 依赖它写消息，`accounts` 依赖它拼首页公告与成员中心提醒。

**什么时候看**：加一种消息 kind、改可见范围口径、改「我的消息」的列与未读计数、动已读回执、
改公告的后台表单，或者排查「这条消息为什么看不见／为什么没消掉」时。

---

## 1. 职责与边界

**负责**

| 面 | 落点 |
|---|---|
| 表与不变量 | `models.py`：`Notice`、`NoticeRead`、`Message` |
| 可见性判定 | `visibility.py`：`public_visible_notices()` / `member_visible_notices(user)`——成员侧可见集合的**唯一出处** |
| 写操作 | `services.py`：标已读／全部已读，八个 kind 的消息写入与撤回 |
| 只读装配 | `selectors.py`：`MessageRow`、`message_rows`、`unread_message_count`、`message_target_url` |
| 页面 | `views.py` + `templates/notices/`：公开公告栏 `notices:public_list` / `public_detail`（匿名可看，挂 `/notices/`）；「我的消息」`member_notices:internal_list` / `internal_detail` / `message_go` / `mark_all_read`（挂 `/member/notices/`） |
| 后台发布 | `admin.py` + `forms.py`：`NoticeAdminForm` 校验范围与用户组的搭配，`save_model` 补发布人并记审计 |
| 成员中心提醒 | `panels.member_home_context()` → `{"unread_messages": ...}` |
| 入口登记 | `apps.py`：向 `core.registry` 注册 `notices.internal`（`sort_order=30`） |

**明确不做**

| 不在这里 | 落在哪 |
|---|---|
| 权限判定 | **本 app 没有 `permissions.py`，也不 import `core.permissions`**：成员页只有 `@login_required`，越权表现为「取不到对象」→ 404，不是 403 |
| @ 提及「提了谁」的解析 | `discussion.mentions.extract_mentions`；本模块只按解析结果对齐消息行 |
| 消息点开后的目标页 | 帖子 `discussion:board`、项目组 `projects:group_detail`、建组申请 `reviews:queue`；`message_go` 只标已读 + 302 |
| 任务的生命周期与历史 | `reviews`：消息只负责「有事等你」，交掉／释放／改派后待办被撤掉，历史留在评审页 |
| 配图／视频的存储与可见性 | `media.MediaFile`：媒体库是**公开件**（落 `mediafiles/`、Nginx 直出、匿名可访问，见 `docs/glossary.md`），公告附件没有权限判定 |
| 强制改密的拦截 | `config.middleware.ForcePasswordChangeMiddleware`；本模块只是被它拦住的页面之一 |
| 事务边界 | 本模块不 `import transaction`、不 `select_for_update`：事件消息写在调用方（`projects` / `reviews` / `discussion`）的事务里，已读是单条幂等写 |
| 已读的审计 | 刻意不写（已读是高频、个人、幂等的操作）。全模块只有后台发布公告写 `notices.create` / `notices.update` |

**依赖方向**

- 上游：`media.models.MediaFile`（`models.py` 顶部 import）、`projects.permissions.is_project_contact`
  （`visibility.py` **模块顶部 import**——这是加载期的实依赖）、`core.registry` / `core.audit`。
  `discussion.selectors.page_of_post`、`reviews.models.ProjectSubmission`、
  `projects.models.GroupJoinRequest` / `GroupCreateRequest` 一律在函数体内局部 import
  （notices 不在加载期依赖 discussion / reviews / projects）。
- `Message` 的五个引用在模型里写成字符串（`"discussion.Post"` 等）：Python 层不 import 对方，
  但**迁移依赖是实的**（`0006_message` 依赖 discussion / projects / reviews 的迁移），
  表间是真正的数据库外键。
- 下游：`discussion.services`（`sync_mention_messages` / `clear_mention_messages`）、
  `reviews.services`（任务与结论）、`projects.services`（申请与结果）来写消息；
  `accounts.views.home` 取最新 5 条公开公告；`templates/accounts/member_home.html` 的提醒条与入口徽标
  按稳定 key `notices.internal` 取 `unread_messages`——注册表是通用的，只有消息带计数，这是页面自己的特例。

---

## 2. 关键接口与失败模式

| 入口 | 语义 | 前置条件 | 失败模式 |
|---|---|---|---|
| `services.mark_read(user, notice)` | 写一条 `NoticeRead`；返回是否新写了回执 | — | 已读过 → `False`，不重复写、不更新 `read_at`；**不校验可见性**（调用方先经可见集合取对象） |
| `services.mark_all_read(user)` | 当前**可见**的未读通知补回执 + 一条 UPDATE 清掉本人全部未读事件消息，返回标了几条 | — | 重复提交第二次返回 0（幂等）；回执用 `bulk_create(ignore_conflicts=True)` 挡并发重复，但返回值按「尝试写了几条」算，并发下会多报 |
| `services.mark_message_read(message)` | 单条事件消息标已读 | — | 已读 → `False`，不重写 `read_at` |
| `services.sync_mention_messages(post, comment, actor, mentioned_users)` | 让某个来源的提及消息与名单**对齐**（缺的写、多的删），返回新写几条 | `post` 必填；`comment=None` 表示帖子正文 | 自己 @ 自己不发；已读状态不因重对齐而复位；`bulk_create` 不触发任何信号 |
| `services.clear_mention_messages(comment)` | 评论软删后撤掉它的提及消息 | — | 只按 `comment=` 删，不碰帖子正文上的提及 |
| `services.notify_preliminary_task` / `notify_review_task` | 给初审人／评审人一条待办 | 任务行已创建 | 同一轮次、同一人、同一阶段 `get_or_create` → 改派走了再回来不攒第二条、也不把已读的重新标未读；`actor` 不写（「来自」列空着） |
| `services.clear_review_task_messages(submission, reviewer=None)` | 撤掉待办消息 | `reviewer=None` 表示撤掉这一轮全部 | 一律 `delete()`，**不看已读** |
| `services.notify_review_result(submission)` | 给 `submission.group.leader` 一条结论 | 只应在轮次落定为 `approved` / `needs_revision` 后调（由 `reviews` 判） | `get_or_create` 幂等（一轮一条）；「已通过／需修改」在渲染时现取 |
| `services.notify_join_request` / `notify_join_result` | 给联系人「待你审核」／给申请人结果 | `join_request` 已存在 | `get_or_create`；`actor` 只在 `defaults` 里，重复调用不会更新它 |
| `services.notify_create_request` / `notify_create_result` | 给**申请这一刻**在册的管理员各一条／给申请人结果 | — | 收件人是快照：之后新建的管理员收不到旧申请；过滤只看两个布尔字段，**已停用的管理员也在收件人里** |
| `selectors.message_rows(user)` | 全部行：置顶通知最前，其余按发生时间倒序混排 | — | 未登录或 `None` → `()`；不认识的 kind **跳过该行**并记 `notice.messages.unknown_kind` warning，不让整页 500 |
| `selectors.unread_message_count(user)` | 未读通知 + 未读事件消息 | — | 未登录 → `0` |
| `selectors.message_target_url(message)` | 某条事件消息的最终去向 | — | kind 不认识 → `None`（调用方转 404） |
| `notices:public_list` / `notices:public_detail` | 匿名公告栏，只看 `scope=public` | — | 要一条 internal / contacts 通知 → 404（公开路由永不暴露内部通知）；`public_detail` 的 GET **不写回执**、不影响未读计数 |
| `member_notices:internal_list` | 「我的消息」整页 | 登录 + 已过强制改密 | 匿名 → 302 到登录页；未改密 → 302 到改密页（中间件） |
| `member_notices:internal_detail` | 看一条可见通知，**GET 即写回执** | 登录 | 不在可见集合 → 404（不是 403）；只有 `@login_required`，没有 `require_GET`——POST 也会写回执 |
| `member_notices:message_go` | 先标已读，再 302 到目标页 | 登录；`recipient=request.user` | 别人的消息 → 404；kind 不认识 → 404；POST → 405 |
| `member_notices:mark_all_read` | POST 标掉全部未读，302 回列表并 flash | 登录；POST | GET（已登录）→ 405；匿名 → 302 到登录页（`@login_required` 在外层） |
| 后台 `admin:notices_notice_add` / `change` | 发布／编辑公告 | Django admin 默认权限位（`NoticeAdmin` 没有自定义 `has_*`） | internal 通知没选用户组、或 public / contacts 通知选了用户组 → 200 重渲染 + 表单错误，不保存；成员 → 302 到后台登录 |

---

## 3. 状态与不变量

### Notice（公告，广播型）

| 字段 | 决定什么 |
|---|---|
| `scope` | `public` / `internal` / `contacts`，决定谁在可见集合里；**数据库没有约束**，靠 `NoticeAdminForm.clean` 保证搭配 |
| `visible_groups` | `auth.Group` 的 M2M，只对 `internal` 生效；用户组是**通知的投递范围，不是身份**（见 `docs/architecture/accounts.md`） |
| `is_pinned` | 排序与「置顶」标记；`Meta.ordering = ("-is_pinned", "-published_at", "-id")` |
| `published_by` | `on_delete=PROTECT`：**发过公告的账号删不掉**；后台新增时被 `save_model` 强制写成 `request.user`，编辑不改 |
| `published_at` | 默认 `timezone.now`（新建时由模型默认填）；**后台只读**（`NoticeAdmin.readonly_fields`），编辑不改。它既排序，也决定这条公告何时出现在首页的最新几条里 |
| `attachments` | `media.MediaFile`（公开件）；`templates/includes/media.html` 直接写 `{{ media.file.url }}`——**附件本身没有可见性判定** |
| 索引 | `(scope, -published_at)` 与 `(scope, -is_pinned, -published_at)` 两条，服务可见集合的查询 |

### NoticeRead（已读回执）

| 字段 | 决定什么 |
|---|---|
| `user` / `notice` | 双 `CASCADE`：删账号或删通知，回执一起走，不留孤儿 |
| `read_at` | 只在新建时写一次 |
| `UniqueConstraint("user", "notice")`（`unique_notice_read_per_user`） | 已读是「有这一行」。**两条写路径**：单条进详情走 `mark_read`（`get_or_create`，幂等）；「全部已读」走 `mark_all_read`（`bulk_create(..., ignore_conflicts=True)`，靠唯一约束去重） |

### Message（事件型消息，一行一个收件人）

| 字段 | 决定什么 |
|---|---|
| `kind` | 八种，见 `KIND_CHOICES`；**每个 kind 必须同时出现在 `Message.KIND_CHOICES`、`selectors._CONTENT_BUILDERS`、`selectors._TYPE_LABELS` 三处**——漏了第二处该行被静默跳过（记 warning），漏了第三处装配时直接 `KeyError`（整页 500） |
| `recipient` | `CASCADE`；`related_name="messages"` |
| `actor` | `SET_NULL`：发起人注销后消息还在，「来自」列变空（`_display_name(None)` → `""`）；评审任务类根本不写 `actor` |
| `is_read` / `read_at` | 只由 `mark_message_read` 与 `mark_all_read` 改；不写审计 |
| 五个可空外键 `post` / `comment` / `submission` / `join_request` / `create_request` | 字符串引用 + 真实数据库外键；来源删除 → `CASCADE` 删行 |
| 组合约束 | **刻意没有**：哪一类消息该挂哪个引用，靠 `services.py` 的写入函数保证，不靠表结构（理由写在模型 docstring 里） |

### 必须成立的断言

- **可见性是查询集，不是权限位**：`member_visible_notices(user)` 是成员侧可见集合的唯一出处，
  列表、详情、未读计数、「全部已读」、置顶排序前的取数全走它；加一条 scope 只改这里。
  它由三段并集构成：`public` ∪ `internal` 且用户组命中 ∪ 我是项目组联系人时的 `contacts`，
  最后 `distinct()` 收掉「一条通知命中我两个组」的重复行。
- **不物化消息副本**：广播型没有「某人有一条通知行」，未读 = 可见通知 − 回执；事件型一行一个收件人、
  没有可见集合可言。所以删除来源后成员侧自然消失——通知删了回执跟着 `CASCADE`，帖子／轮次／申请删了消息行跟着走。
- **事件消息的四个可显示字段（标题／链接／来自／说明）一律现取现算**：帖子改了标题、轮次出了新结论、
  申请通过了，消息里跟着变；行里只有结构化引用与已读状态。
- **进入详情即已读**：`internal_detail` 的 GET 写回执（`mark_read` 幂等），公开公告栏那条路不写——
  同一条公开通知，在公告栏看多少次都不会消掉「我的消息」里的未读角标。
- **已读与撤回是两条路**：撤回（`clear_review_task_messages` / `clear_mention_messages`）直接 `delete()`，
  不看已读状态；重对齐（`sync_mention_messages`）只增删行，**不把留下的人重新标成未读**。
- **后台表单是「范围 × 用户组」搭配的唯一执行点**：`internal` 必须至少一个用户组，`public` / `contacts`
  不许带用户组。`Notice` 没有模型级 `clean()`，`save()` 也不跑 `full_clean()`——绕过 admin 能造出
  永远不可见的 internal 通知，或带着用户组但照常对所有人可见的 public 通知。
- **审计只有两条**：后台发布公告写 `notices.create`，编辑写 `notices.update`，都在 `save_model` 里、
  与保存同一次请求；其余写操作（含全部已读）不写审计。

---

## 4. 数据流与时序

**广播型：一条公告从后台到「我的消息」**

1. 管理员在后台保存 → `NoticeAdmin.save_model`：新增分支把 `published_by` 设成 `request.user`，
   写 `notices.create` / `notices.update` 审计，再记一条 `admin.notice.save` 日志。
2. 公开侧：`notices:public_list` / `public_detail` 用 `public_visible_notices()`（只 `scope=public`），
   匿名可看；`accounts:home` 也取它（`[:5]`）拼首页的最新公告。
3. 成员侧：`member_notices:internal_list` → `selectors.message_rows(user)` → `_notice_rows` 用
   `member_visible_notices(user)` 实时查，已读来自一次性取回的 `NoticeRead.notice_id` 集合。
4. 点进详情 → `services.mark_read` 补回执；未读样式与计数只认回执。
5. 「全部已读」→ POST `mark_all_read`：先与现状比对补回执，再一条 UPDATE 清事件消息；
   视图 flash 一句并 302 回列表。模板在没有未读时不渲染这个按钮（`{% if unread_count %}`）。

**事件型：一行怎么产生、怎么消失**

1. 调用方**在自己的事务里**调 `notices.services`（没有信号、没有队列、没有异步任务）：
   `projects`（入组／建组申请与结果）、`reviews`（任务分配与改派、结论、一票定论）、
   `discussion`（提及）。
2. 写入一律 `get_or_create` 或对齐：同一来源、同一收件人、同一 kind 只一行；重复调用幂等。
   任务改派 = 撤原持有人 + 写新持有人，改派回来靠 `get_or_create` 不攒第二条。
3. 装配：`_event_rows` 按 `kind` 从 `_CONTENT_BUILDERS` 取渲染函数现算四个字段，
   `url` 一律指 `member_notices:message_go`——**目标页（帖子、项目组）并不认识这条消息**，
   「点开即已读」只能在中转处成立。
4. 点击：`message_go` 先 `mark_message_read`（写 `is_read` / `read_at`）再 302。帖子落在
   `?page=N#post-<pk>` / `#comment-<pk>`（页码与列表观感一致，见 `discussion.selectors.page_of_post`），
   入组申请去项目组详情，建组申请去 `reviews:queue`。
5. 消失有三条路：来源删除走 FK `CASCADE`；任务交掉／释放／改派走 `clear_review_task_messages`；
   评论软删走 `clear_mention_messages`。

**提及：解析与消息分家**

1. `discussion.mentions.extract_mentions(text)` 只回答「提了谁」——认 `Profile.full_name`、不认账号名，
   最长匹配，`@` 前不能是字母数字（邮箱不算）。
2. `discussion.services._sync_mentions` 在**发帖、编辑帖子、发评论**三处调 `sync_mention_messages`，
   按 `(kind=mention, post, comment)` 对齐；`comment=None` 是帖子正文上的提及，评论上的提及以评论为界、互不影响。
3. 编辑是**对齐**不是追加：被去掉的人那一行直接删（已读的也删），留下的人原样不动。
4. 评论软删后内容还在库里但界面看不到，消息点过去只会看到「该评论已删除」——所以单独撤掉，不提醒。

---

## 5. 错误处理与诊断

**领域异常：本模块一个都没有。** `services.py` 全是「写／查，返回布尔或计数」，
不抛业务异常，调用方（`projects` / `reviews` / `discussion`）不需要为它写 `except`。

**拒绝形态**（页面上的实际表现）：

| 情形 | 表现 |
|---|---|
| 看公开公告栏／公开详情 | 200；`scope=public` 之外的通告在这条路上 404 |
| 匿名打成员页 | 302 到 `accounts:login`（带 `next`） |
| `must_change_password=True` 的成员打成员页 | 302 到 `accounts:password_change`（中间件，不是本模块） |
| 成员要一条不在自己可见集合里的通知 | 404（可见性是查询集，取不到就是取不到，**没有 403**） |
| `message_go` 别人的消息 | 404（`get_object_or_404(Message, pk=..., recipient=request.user)`） |
| `message_go` 遇到不认识的 kind | 404（`message_target_url` 返回 `None`，视图 `raise Http404`） |
| 已登录 GET 打 `mark_all_read`、POST 打 `message_go` | 405 |
| 后台表单里 internal 没用户组／public、contacts 带用户组 | 200 重渲染 + 表单错误，不保存 |
| 成员打开 `/admin/` | 302 到后台登录 |
| 数据里出现不认识的 kind | 列表跳过该行并记 warning，页面 200——不让降级部署留下的行把整页打成 500 |

**审计 action**（`core.audit.record_audit`，**发过的字符串不再改**）：

| action | 触发点 |
|---|---|
| `notices.create` | 后台新增公告（`NoticeAdmin.save_model` 的 `not change` 分支） |
| `notices.update` | 后台编辑公告 |

`detail` 记 `{"scope", "is_pinned"}`。已读、消息的写入与撤回、全部已读**都不写审计**——
`models.NoticeRead` 与 `services.py` 的 docstring 各用一句话钉着这条。

**日志**：`notices.views` 与 `notices.selectors` 各一个 `logging.getLogger(__name__)`。
关键事件名：`notice.list.view` / `notice.detail.view`（带 `scope=public|internal`）、
`notice.messages.list`、`notice.messages.read_all`、`notice.messages.open`、`admin.notice.save`、
`notice.messages.unknown_kind`（warning）。视图层的都带 `extra={"request_id": ...}`；
`selectors` 那条 warning 不带（取数层拿不到 request）。

**级别**：`config/settings.py` 的 `LOGGING["loggers"]` 里有 `notices` 这一节，`DEBUG` 级、
`console` + `file` 两个 handler，所以上面这些事件都落 `logs/django.log`（`config/tests.py` 的
`AppLoggerTests` 盯着这条：哪一节被删掉、或新增 app 忘了配，测试会红）。早先这几节是缺的，
info 连级别检查都过不去、warning 只经 `lastResort` 到 stderr——排查时会以为「什么都没发生」。

**刻意不报错**：

- 重复标已读、「全部已读」提交两次 → no-op，返回 `False` / 计数归零，页面照常；
- 重复调用任何 `notify_*` → `get_or_create` 命中，不新增行、不动已读状态；
- 被撤销的提及 → 消息行直接删掉，不留「已撤销」痕迹；
- 未登录时 `message_rows` / `unread_message_count` → `()` / `0`（函数自己不抛异常）。

---

## 6. 测试要点与已知限制

### 测试（`notices/tests.py`，按类看）

| 类 | 钉住什么 |
|---|---|
| `NoticeVisibilityAcceptanceTests` | 公开路由永不暴露 internal / contacts；internal 按用户组命中（任一命中即可）、别的组和无组都看不见；联系人才看 contacts；未改密成员被中间件挡回；首页只出公开通知；置顶排最前 |
| `MessageReadStateTests` | 行只含该用户可见的通知；行带类型／来自／说明／已读；联系人说明是「仅项目组联系人」；内部通知列出全部命中的组名；没有姓名时「来自」回落账号；计数只算可见未读；标已读幂等；「全部已读」只动本人可见的；删通知后行、计数、回执一起消失 |
| `EventMessageAggregationTests` | 提及行的类型／来自／说明与 `message_go` 链接；评论提及落到 `#comment-<pk>` 锚点；置顶最前、其余按时间混排；计数把两类相加；「全部已读」两类都清；`message_go` 别人的消息 404；不认识的 kind 跳过而不炸页 |
| `MemberHomeReminderAcceptanceTests` | 成员中心入口叫「我的消息」；有未读才有提醒条与徽标且带计数；全读完什么都不渲染；别的组的未读不触发提醒 |
| `MessagePageAcceptanceTests` | 五列（类型／标题／来自／说明／时间）；未读行 `class="unread"` 与「N 条未读」；点详情清未读标记且只留一条回执；「全部已读」的 flash 与 POST-only；没有未读时不渲染按钮；删通知后页面少一行 |
| `NoticeAdminAcceptanceTests` | 后台发布记 `published_by` 与 `notices.create` 审计；internal 没用户组、public / contacts 带用户组都拒绝保存；contacts 不带组可存；成员进不了后台 |

### 已知限制 / 当前不支持

- **本模块没有任何权限判定**（没有 `permissions.py`，也不 import `core.permissions`）：成员页门槛只有
  `@login_required`。以后要加「只有谁能做什么」的页面动作，判定应落 `core.permissions` 或新建
  `permissions.py`，别写在视图里——否则可见性就有了第二处真相。
- **「internal 必须有用户组」只在后台表单把关**：数据库与模型都没有这条约束。绕过 admin 建出的
  internal 通知对所有成员都不可见（`visible_groups` 为空，交集为空）；带用户组的 public / contacts
  通知照常对所有人可见（用户组被忽略）。
- **公告附件没有可见性判定**：`attachments` 指向公开媒体库，URL 由 Nginx 直出。内部通知的正文受可见集合
  保护，配图不在这道保护里——往内部／联系人通知挂配图时要知道这一点。
- **`notify_create_request` 的收件人是申请那一刻的管理员快照**，过滤写成
  `Q(is_staff=True) | Q(is_superuser=True)`：之后才建的管理员收不到旧申请；被停用的管理员仍在收件人里
  （没有 `is_active` 过滤）。这份内联口径与 `core.permissions.is_admin` 目前一致，但改后者不会自动改这里。
- **`internal_detail` 是 GET 写库**：没有 `require_GET` / `require_POST`，POST 同样会写回执。
  回执幂等、写的是本人的行，风险可控，但「这个 URL 是只读的」不成立。
- **「我的消息」不分页**：`message_rows` 一次装配全部行，每装配一条提及还要查一次它所在帖子的页码
  （`page_of_post` 会把该板块的帖子 id 全捞进内存）。提及多的账号打开这一页要按行数付查询。
- **编辑帖子会真的删掉提及消息**：不再被提到的人直接 `delete()`，已读的也删——「我的消息」里不会留下
  「这条提及已撤销」的痕迹。这是刻意的对齐语义，但改它要连带考虑已读与计数的一致。
- **`Message` 的五个引用没有组合约束**：哪一类消息挂哪个引用是 `services.py` 写入函数的责任
  （模型 docstring 明说）。绕过 services 直接建行能造出渲染不出来或语义错乱的消息；加新 kind 时
  三处（`KIND_CHOICES`、`_TYPE_LABELS`、`_CONTENT_BUILDERS`）必须同时改。
- **`mark_all_read` 的返回计数**是「尝试写的回执数 + 被 UPDATE 的事件消息数」，并发下可能多报
  （回执被 `ignore_conflicts` 挡掉，但计数已经算进去了）。这个数只用于日志，不影响页面。
- **`list.html` 今天只服务公开列表**：它带 `detail_namespace` / `detail_name` 两个参数、范围列直接写
  `{{ notice.scope }}`、不写已读回执——把成员侧的通知接进这一页会同时丢掉回执与范围口径。
  成员侧另有 `message_list.html`。
- **已读回执没有清理入口**：只随通知／账号级联删除，没有「清理 N 天前的回执」这类命令。
