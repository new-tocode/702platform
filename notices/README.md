# notices 模块

> 站内通知与消息：管理员发布的**公告**（`Notice`，三种可见范围）、成员侧的「我的消息」页、
> **事件型消息**（`Message`，一行一个收件人），以及其中唯一一种由成员自己发起的**私信**
> （`DirectMessage`，正文单独一张表）。可见性收敛在 `visibility.py` 一处；公告由后台发布，
> 别的事件的消息由别的 app 在自己的事务里调 `services.py` 写入。
> **它不判「谁能做什么」**（本 app 没有 `permissions.py`），不解析 @ 提及（归 `discussion.mentions`），
> 不渲染**别的 app** 的消息点开后那一页（帖子／项目组／评审队列各归其主；私信没有别的主人，
> 它的详情页归本模块），也不替别的 app 写事务与审计。
> `discussion`、`reviews`、`projects` 依赖它写消息，`accounts` 依赖它拼首页公告、成员中心提醒，
> 以及只读资料页上的写私信入口。

**什么时候看**：加一种消息 kind、改可见范围口径、改「我的消息」的列与未读计数、动已读回执、
改公告的后台表单、碰私信（正文上限、读完的处置、浮动窗），
或者排查「这条消息为什么看不见／为什么没消掉」时。

---

## 1. 职责与边界

**负责**

| 面 | 落点 |
|---|---|
| 表与不变量 | `models.py`：`Notice`、`NoticeRead`、`Message`、`DirectMessage` |
| 可见性判定 | `visibility.py`：`public_visible_notices()` / `member_visible_notices(user)`——成员侧可见集合的**唯一出处** |
| 写操作 | `services.py`：标已读／全部已读，九个 kind 的消息写入与撤回，私信的发送与删除 |
| 只读装配 | `selectors.py`：`MessageRow`、`message_rows`、`unread_message_count`、`message_target_url`、`display_name` |
| 页面 | `views.py` + `templates/notices/`：公开公告栏 `notices:public_list` / `public_detail`（匿名可看，挂 `/notices/`）；「我的消息」`member_notices:internal_list` / `internal_detail` / `message_go` / `mark_all_read`；私信 `direct_compose`（整页与浮动窗共用）/ `direct_detail` / `direct_delete`（都挂 `/member/notices/`） |
| 后台发布 | `admin.py` + `forms.py`：`NoticeAdminForm` 校验范围与用户组的搭配，`save_model` 补发布人并记审计 |
| 成员中心提醒 | `panels.member_home_context()` → `{"unread_messages": ...}` |
| 别处页面上的写私信窗口 | `panels.direct_compose_context()` → `{"direct_form": ...}`；窗口本体在 `templates/includes/direct_compose.html`（跨应用共用件），打开它的是 `static/js/direct_compose.js` |
| 入口登记 | `apps.py`：向 `core.registry` 注册 `notices.internal`（`sort_order=30`） |

**明确不做**

| 不在这里 | 落在哪 |
|---|---|
| 权限判定 | **本 app 没有 `permissions.py`，也不 import `core.permissions`**：成员页只有 `@login_required`，越权表现为「取不到对象」→ 404，不是 403 |
| @ 提及「提了谁」的解析 | `discussion.mentions.extract_mentions`；本模块只按解析结果对齐消息行 |
| 别的 app 的消息点开后的目标页 | 帖子 `discussion:board`、项目组 `projects:group_detail`、建组申请 `reviews:queue`；`message_go` 只标已读 + 302。私信不在此列——它的详情页就是本模块的 `direct_detail` |
| 任务的生命周期与历史 | `reviews`：消息只负责「有事等你」，交掉／释放／改派后待办被撤掉，历史留在评审页 |
| 配图／视频的存储与可见性 | `media.MediaFile`：媒体库是**公开件**（落 `mediafiles/`、Nginx 直出、匿名可访问，见 `../docs/术语表.md`），公告附件没有权限判定 |
| 强制改密的拦截 | `config.middleware.ForcePasswordChangeMiddleware`；本模块只是被它拦住的页面之一 |
| 事务边界（**分两种，别按「一律」记**） | 别的 app 发起的消息写在**调用方**（`projects` / `reviews` / `discussion`）的事务里，本模块不开事务；已读是单条幂等写；**私信是本模块自己发起的写**，正文与通知两行必须一起落，所以那一处自己开事务。本模块不 `select_for_update` |
| 私信的正文与收发关系 | 不进后台、不写审计（见 §5）：正文与「谁写给谁」是成员之间的东西，不是给运维留痕的。本模块因此也没有 `DirectMessageAdmin` |
| 已读的审计 | 刻意不写（已读是高频、个人、幂等的操作）。全模块只有后台发布公告写 `notices.create` / `notices.update` |

**依赖方向**

- 上游：`media.models.MediaFile`（`models.py` 顶部 import）、`projects.permissions.is_project_contact`
  （`visibility.py` **模块顶部 import**——这是加载期的实依赖）、`core.registry` / `core.audit`。
  `discussion.selectors.page_of_post`、`reviews.models.ProjectSubmission`、
  `projects.models.GroupJoinRequest` / `GroupCreateRequest` 一律在函数体内局部 import
  （notices 不在加载期依赖 discussion / reviews / projects）。
- `Message` 里指向别的 app 的五个引用在模型里写成字符串（`"discussion.Post"` 等）：Python 层不
  import 对方，但**迁移依赖是实的**（`0006_message` 依赖 discussion / projects / reviews 的迁移），
  表间是真正的数据库外键。第六个引用 `direct_message` 指回本 app 的 `DirectMessage`，直接写类名。
- 下游：`discussion.services`（`sync_mention_messages` / `clear_mention_messages`）、
  `reviews.services`（任务与结论）、`projects.services`（申请与结果）来写消息；
  `accounts.views.home` 取最新 5 条公开公告；`templates/accounts/member_home.html` 的提醒条与入口徽标
  按稳定 key `notices.internal` 取 `unread_messages`——注册表是通用的，只有消息带计数，这是页面自己的特例。
- `accounts.views.member_profile_readonly` 在**函数体内**局部 import `notices.panels`
  取那只私信表单（与 `member_home` 取未读计数同一处口子），所以加载期没有新的依赖方向；
  模板那一侧另有 `templates/accounts/member_profile_readonly.html` 直接 reverse
  `member_notices:direct_compose`——与它 reverse `accounts:member_profile` 是同一件事。

---

## 2. 关键接口与失败模式

| 入口 | 语义 | 前置条件 | 失败模式 |
|---|---|---|---|
| `services.send_direct_message(sender, recipient, body)` | 发一条私信：正文一行 + 收件人那条通知一行，**同一事务**；返回那条 `Message` | 两个账号都在册；`sender != recipient` | 给自己发 → `ValueError`（视图先拦成一句 flash）；超长正文不在这里拦——那是表单与模型的 `max_length`（见 §6 已知限制） |
| `services.delete_direct_message(message)` | 收件人主动删一条私信：删正文那一行，通知行跟着 `CASCADE` | `message.kind == DIRECT`（由视图过滤） | 正文缺失的坏行只删通知行，不留一条删不掉的行 |
| `services.mark_read(user, notice)` | 写一条 `NoticeRead`；返回是否新写了回执 | — | 已读过 → `False`，不重复写、不更新 `read_at`；**不校验可见性**（调用方先经可见集合取对象） |
| `services.mark_all_read(user)` | 当前**可见**的未读通知补回执 + 一条 UPDATE 清掉本人全部未读事件消息，返回标了几条 | — | 重复提交第二次返回 0（幂等）；回执用 `bulk_create(ignore_conflicts=True)` 挡并发重复，但返回值按「尝试写了几条」算，并发下会多报 |
| `services.mark_message_read(message)` | 单条事件消息标已读 | — | 已读 → `False`，不重写 `read_at` |
| `services.sync_mention_messages(post, comment, actor, mentioned_users)` | 让某个来源的提及消息与名单**对齐**（缺的写、多的删），返回新写几条 | `post` 必填；`comment=None` 表示帖子正文 | 自己 @ 自己不发；已读状态不因重对齐而复位；`bulk_create` 不触发任何信号 |
| `services.clear_mention_messages(comment)` | 评论软删后撤掉它的提及消息 | — | 只按 `comment=` 删，不碰帖子正文上的提及 |
| `services.notify_comment(comment, actor)` | 有人评论了你的帖子：给帖子作者一条「评论」 | `comment.post` 必须能取到作者；调用方**先写提及**再调它 | 自己评论自己的帖子不发；评论里已经 @ 到帖主时也不发（那条提及更具体）；同一条评论 `get_or_create` 幂等 |
| `services.clear_comment_messages(comment)` | 评论软删后撤掉帖主收到的那条 | — | 只按 `comment=` 删，与提及各撤各的 |
| `services.notify_preliminary_task` / `notify_review_task` | 给初审人／评审人一条待办 | 任务行已创建 | 同一轮次、同一人、同一阶段 `get_or_create` → 改派走了再回来不攒第二条、也不把已读的重新标未读；`actor` 不写（「来自」列空着） |
| `services.clear_review_task_messages(submission, reviewer=None)` | 撤掉待办消息 | `reviewer=None` 表示撤掉这一轮全部 | 一律 `delete()`，**不看已读** |
| `services.notify_review_result(submission)` | 给 `submission.group.leader` 一条结论 | 只应在轮次落定为 `approved` / `needs_revision` 后调（由 `reviews` 判） | `get_or_create` 幂等（一轮一条）；「已通过／需修改」在渲染时现取 |
| `services.notify_join_request` / `notify_join_result` | 给联系人「待你审核」／给申请人结果 | `join_request` 已存在 | `get_or_create`；`actor` 只在 `defaults` 里，重复调用不会更新它 |
| `services.notify_create_request` / `notify_create_result` | 给**申请这一刻**在册的管理员各一条／给申请人结果 | — | 收件人是快照：之后新建的管理员收不到旧申请；过滤只看两个布尔字段，**已停用的管理员也在收件人里** |
| `selectors.message_rows(user)` | 全部行：置顶通知最前，其余按发生时间倒序混排 | — | 未登录或 `None` → `()`；不认识的 kind **跳过该行**并记 `notice.messages.unknown_kind` warning，不让整页 500 |
| `selectors.unread_message_count(user)` | 未读通知 + 未读事件消息 | — | 未登录 → `0` |
| `selectors.message_target_url(message)` | 某条事件消息的最终去向 | — | kind 不认识、或来源缺了（今天只有「没有正文的私信」）→ `None`（调用方转 404） |
| `notices:public_list` / `notices:public_detail` | 匿名公告栏，只看 `scope=public` | — | 要一条 internal / contacts 通知 → 404（公开路由永不暴露内部通知）；`public_detail` 的 GET **不写回执**、不影响未读计数 |
| `member_notices:internal_list` | 「我的消息」整页 | 登录 + 已过强制改密 | 匿名 → 302 到登录页；未改密 → 302 到改密页（中间件） |
| `member_notices:internal_detail` | 看一条可见通知，**GET 即写回执** | 登录 | 不在可见集合 → 404（不是 403）；只有 `@login_required`，没有 `require_GET`——POST 也会写回执 |
| `member_notices:message_go` | 先标已读，再 302 到目标页 | 登录；`recipient=request.user` | 别人的消息 → 404；kind 不认识 → 404；POST → 405 |
| `member_notices:mark_all_read` | POST 标掉全部未读，302 回列表并 flash | 登录；POST | GET（已登录）→ 405；匿名 → 302 到登录页（`@login_required` 在外层） |
| `member_notices:direct_compose` | 写私信：GET 出表单，POST 发送。**一个地址两种外壳**——整页表单与页面上的浮动窗共用它（脚本把窗口表单的 action 指到这里） | 登录；收信人 `is_active=True` | 收信人不存在或已停用 → 404；给自己发 → flash + 302（不是 4xx）；正文空／超长 → 200 重渲染，写过的正文还在；成功 → 302 回 `next`（只认站内）并 flash；非 GET/POST → 405 |
| `member_notices:direct_detail` | 私信全文（读完**不消失**），GET 即已读 | 登录；`recipient=request.user` | 不是我的、不是私信、正文缺了 → 404；非 GET → 405 |
| `member_notices:direct_delete` | 收件人主动删除一条私信（正文与通知一起走） | 登录；POST；`recipient=request.user` | 同上三条 → 404；GET → 405 |
| 后台 `admin:notices_notice_add` / `change` | 发布／编辑公告 | Django admin 默认权限位（`NoticeAdmin` 没有自定义 `has_*`） | internal 通知没选用户组、或 public / contacts 通知选了用户组 → 200 重渲染 + 表单错误，不保存；成员 → 302 到后台登录 |

---

## 3. 状态与不变量

### Notice（公告，广播型）

| 字段 | 决定什么 |
|---|---|
| `scope` | `public` / `internal` / `contacts`，决定谁在可见集合里；**数据库没有约束**，靠 `NoticeAdminForm.clean` 保证搭配 |
| `visible_groups` | `auth.Group` 的 M2M，只对 `internal` 生效；用户组是**通知的投递范围，不是身份**（见 [`../accounts/README.md`](../accounts/README.md) §7） |
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
| `kind` | 十种，见 `KIND_CHOICES`；**每个 kind 必须同时出现在 `Message.KIND_CHOICES`、`selectors._CONTENT_BUILDERS`、`selectors._TYPE_LABELS` 三处**——漏了第二处该行被静默跳过（记 warning），漏了第三处装配时直接 `KeyError`（整页 500） |
| `recipient` | `CASCADE`；`related_name="messages"` |
| `actor` | `SET_NULL`：发起人注销后消息还在，「来自」列变空（`_display_name(None)` → `""`）；评审任务类根本不写 `actor` |
| `is_read` / `read_at` | 只由 `mark_message_read` 与 `mark_all_read` 改；不写审计 |
| 六个可空外键 `post` / `comment` / `submission` / `join_request` / `create_request` / `direct_message` | 前五个是字符串引用（跨 app），`direct_message` 直接写类名（同 app）；都是真实数据库外键，来源删除 → `CASCADE` 删行 |
| 组合约束 | **刻意没有**：哪一类消息该挂哪个引用，靠 `services.py` 的写入函数保证，不靠表结构（理由写在模型 docstring 里） |

### DirectMessage（私信正文，一条一行）

| 字段 | 决定什么 |
|---|---|
| `sender` | `SET_NULL`：发信人注销后私信还在，「来自」为空、也不再有可回的人（行上的「快速回信」跟着不出现）。与 `Message.actor` 同一个口径 |
| `recipient` | `CASCADE`：收信人没了，他收到的私信一起走（不会有人再看） |
| `body` | 正文，`max_length=DIRECT_MESSAGE_MAX_CHARS`（1500）。**这是全文唯一的家**——通知行指过来，不复制 |
| `created_at` | 既排序也显示（`Meta.ordering = ("-created_at", "-pk")`） |
| 索引 / 组合约束 | 都没有：今天没有「按人查私信」的路径，收发都经 `Message` 行，不预先建索引（理由同 `Message` 的组合约束） |

### 必须成立的断言

- **可见性是查询集，不是权限位**：`member_visible_notices(user)` 是成员侧可见集合的唯一出处，
  列表、详情、未读计数、「全部已读」、置顶排序前的取数全走它；加一条 scope 只改这里。
  它由三段并集构成：`public` ∪ `internal` 且用户组命中 ∪ 我是项目组联系人时的 `contacts`，
  最后 `distinct()` 收掉「一条通知命中我两个组」的重复行。
- **不物化消息副本**：广播型没有「某人有一条通知行」，未读 = 可见通知 − 回执；事件型一行一个收件人、
  没有可见集合可言。所以删除来源后成员侧自然消失——通知删了回执跟着 `CASCADE`，帖子／轮次／申请删了消息行跟着走。
- **事件消息的四个可显示字段（标题／链接／来自／说明）一律现取现算**：帖子改了标题、轮次出了新结论、
  申请通过了，消息里跟着变；行里只有结构化引用与已读状态。私信的四个字段同样现算，正文取自
  `DirectMessage`——「正文没有第二个家」与「消息行不存副本」是同一条性质的两种说法。
- **私信的两行同生同死**：`send_direct_message` 在一个事务里写正文与通知；删除走
  `delete_direct_message` 删正文、通知行跟着 `CASCADE`。所以「我的消息」里出现过的私信行，
  背后必有一条正文（**除非**绕过写入函数直接建行——那种行装配时被跳过，见 §5）。
- **私信读完不消失**：已读只动 `is_read` / `read_at`，列表照样列着那条行（只是不再高亮）。
  要它走只有一条路——收信人在 `direct_detail` 上按「删除私信」（`direct_delete`，POST）。
  这与「来源删除即级联删行」并不冲突：那一头是**别的 app 删了自己的东西**，这一头是**收信人自己动手**。
- **一条私信只给收信人一行**：发信人自己的「我的消息」里不会有它（要看见，得等对方回一条）。
  私信也不进「已发送」这类列表——本模块没有那张表。
- **进入详情即已读**：`internal_detail` 的 GET 写回执（`mark_read` 幂等），公开公告栏那条路不写——
  同一条公开通知，在公告栏看多少次都不会消掉「我的消息」里的未读角标。
- **已读与撤回是两条路**：撤回（`clear_review_task_messages` / `clear_mention_messages` /
  `clear_comment_messages`）直接 `delete()`，不看已读状态；重对齐（`sync_mention_messages`）只增删行，
  **不把留下的人重新标成未读**。
- **一条评论最多给帖主一条消息**：他自己评论自己的帖子不发；别人在评论里 @ 到了他，也只留那条提及
  （`notify_comment` 先查同一条评论上有没有给他的提及）。为此 `discussion` 那边必须**先写提及、再调
  `notify_comment`**——顺序反了就会同一条评论并列两条。
- **后台表单是「范围 × 用户组」搭配的唯一执行点**：`internal` 必须至少一个用户组，`public` / `contacts`
  不许带用户组。`Notice` 没有模型级 `clean()`，`save()` 也不跑 `full_clean()`——绕过 admin 能造出
  永远不可见的 internal 通知，或带着用户组但照常对所有人可见的 public 通知。
- **审计只有两条**：后台发布公告写 `notices.create`，编辑写 `notices.update`，都在 `save_model` 里、
  与保存同一次请求；其余写操作（含全部已读与**私信的发送／删除**）不写审计。私信是刻意的（见 §5）：
  审计表只追加、删不掉，把成员之间的收发关系记进去，等于给它配一份永久的底账。

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
   `discussion`（提及、评论）。
2. 写入一律 `get_or_create` 或对齐：同一来源、同一收件人、同一 kind 只一行；重复调用幂等。
   任务改派 = 撤原持有人 + 写新持有人，改派回来靠 `get_or_create` 不攒第二条。
3. 装配：`_event_rows` 按 `kind` 从 `_CONTENT_BUILDERS` 取渲染函数现算四个字段，
   `url` 一律指 `member_notices:message_go`——**别的 app 的目标页（帖子、项目组）并不认识这条消息**，
   「点开即已读」只能在中转处成立。私信也走这一跳（`message_target_url` 给它的是本模块的详情页），
   于是「行的链接长什么样」在装配层只有一个形状。
4. 点击：`message_go` 先 `mark_message_read`（写 `is_read` / `read_at`）再 302。帖子落在
   `?page=N#post-<pk>` / `#comment-<pk>`（页码与列表观感一致，见 `discussion.selectors.page_of_post`），
   入组申请去项目组详情，建组申请去 `reviews:queue`。
5. 消失有三条路：来源删除走 FK `CASCADE`；任务交掉／释放／改派走 `clear_review_task_messages`；
   评论软删走 `clear_mention_messages` + `clear_comment_messages`。

**提及：解析与消息分家**

1. `discussion.mentions.extract_mentions(text)` 只回答「提了谁」——认 `Profile.full_name`、不认账号名，
   最长匹配，`@` 前不能是字母数字（邮箱不算）。
2. `discussion.services._sync_mentions` 在**发帖、编辑帖子、发评论**三处调 `sync_mention_messages`，
   按 `(kind=mention, post, comment)` 对齐；`comment=None` 是帖子正文上的提及，评论上的提及以评论为界、互不影响。
3. 编辑是**对齐**不是追加：被去掉的人那一行直接删（已读的也删），留下的人原样不动。
4. 评论软删后内容还在库里，但页面上整条不再渲染（默认经理只给未删的）——消息点过去落不到那句话，
   所以单独撤掉，不提醒。

**私信：从写私信到读完、回信、删除**

1. 页面上的入口（成员资料页的「私信」、消息行上的「快速回信」、详情页的「回复」）都是指向
   `member_notices:direct_compose` 的**普通链接**：没有脚本时打开整页表单，有脚本时
   `static/js/direct_compose.js` 拦下点击、把收件人与提交地址从那条链接上取下来，打开
   `templates/includes/direct_compose.html` 里的 `<dialog>`。**两条路进同一个视图**，
   所以发送、校验、拒绝只有一处。
2. `direct_compose` 校验通过 → `services.send_direct_message`：一个事务里写 `DirectMessage`
   （正文）与 `Message`（`kind=direct`、`recipient`、`actor`、`direct_message`）。收件人的未读数
   因此当场 +1，成员中心的提醒条与徽标下一次渲染就带上它——**它走的还是所有事件消息那条路**，
   没有第二套「新消息提示」。
3. 收件人在「我的消息」看到一行（类型「私信」、来自发信人、说明是正文节选），点它 → `message_go`
   标已读 → 302 到 `direct_detail`。已读只改标记：**行还在列表里**。
4. 详情页上「回复」= 同一条 `direct_compose`（收件人是原发信人），发出去就是一条**普通私信**；
   「删除私信」= POST `direct_delete` → 删正文、通知行跟着 `CASCADE` 走，回列表并 flash。

**评论：帖主那条从哪来**

1. 同一处 `discussion.services.create_comment` 里，`_sync_mentions` 之后紧跟一句 `notify_comment`：
   收件人是 `comment.post.author`，`actor` 是评论人，`post` / `comment` 两个引用都写上。
2. 两条去重规则都在 `notify_comment` 里：自己评论自己的帖子、以及评论里已经 @ 到帖主，都不写。
3. 评论不能编辑，所以这条消息只写不撤；撤回与提及同步发生——软删评论时两个 `clear_*` 一起调。

---

## 5. 错误处理与诊断

**领域异常：本模块一个都没有。** `services.py` 全是「写／查，返回布尔或计数」，
不抛业务异常，调用方（`projects` / `reviews` / `discussion`）不需要为它写 `except`。
唯一会抛的是 `send_direct_message` 收到 `sender == recipient` 时的 `ValueError`——
那是编程错误（页面上的入口对自己根本不显示，视图另有一句 flash），不是给用户看的拒绝。

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
| 给自己发私信 | flash「不能给自己发私信。」+ 302 回原来那页（**业务拒绝不是 4xx**，与项目组那边的领域异常同一口径） |
| 私信收信人不存在或已停用 | 404（`is_active=True` 的过滤，与只读资料页同一道门） |
| 私信不是我的／不是私信／正文缺了 | 404（`get_object_or_404(..., recipient=request.user, kind=DIRECT)`） |
| 私信正文空／超长 | 200 重渲染写私信那一页 + 表单错误，**写过的正文还在** |
| 数据里出现没有正文的私信行 | 列表跳过该行并记 `notice.messages.missing_source` warning；点它（`message_go`）与其详情页都 404，页面 200 |
| GET 打 `direct_delete`、POST 打 `direct_detail` | 405 |
| 发完私信带的 `next` 是外站地址 | 忽略它，回「我的消息」（`url_has_allowed_host_and_scheme`，与改密页同一个口径） |

**审计 action**（`core.audit.record_audit`，**发过的字符串不再改**）：

| action | 触发点 |
|---|---|
| `notices.create` | 后台新增公告（`NoticeAdmin.save_model` 的 `not change` 分支） |
| `notices.update` | 后台编辑公告 |

`detail` 记 `{"scope", "is_pinned"}`。已读、消息的写入与撤回、全部已读**都不写审计**——
`models.NoticeRead` 与 `services.py` 的 docstring 各用一句话钉着这条。

**私信的发送与删除也不写审计**，理由是新的，单独记一笔：审计表只追加、删不掉（触发器守着，见
[`../docs/更新维护/开发与部署.md`](../docs/更新维护/开发与部署.md) §6），把「谁在什么时候给谁发了私信」
记进去，等于给成员之间的往来配一份永久底账，而它与平台要追责的那些动作（发布公告、改资格）不是一回事。
正文更不进日志——日志只记 `message_id`、收发双方的账号 id 与字数。

**日志**：`notices.views` 与 `notices.selectors` 各一个 `logging.getLogger(__name__)`。
关键事件名：`notice.list.view` / `notice.detail.view`（带 `scope=public|internal`）、
`notice.messages.list`、`notice.messages.read_all`、`notice.messages.open`、`admin.notice.save`、
`notice.messages.unknown_kind`（warning，装配层）、
私信的 `notice.messages.direct.send` / `.view` / `.delete`（INFO）与 `.reject`（warning，表单没过）、
`notice.messages.missing_source`（warning，装配层）。
视图层的都带 `extra={"request_id": ...}`；`selectors` 那两条 warning 不带（取数层拿不到 request）。
**正文不进日志**：私信那几条只记 `message_id`、账号 id 与字数。

**级别**：`config/settings.py` 的 `LOGGING["loggers"]` 里有 `notices` 这一节，`DEBUG` 级、
`console` + `file` 两个 handler，所以上面这些事件都落 `logs/django.log`（`config/tests.py` 的
`AppLoggerTests` 盯着：配置节被删、运行时没接上那个文件、或真发一条 `INFO` 却没落盘，测试都会红）。
早先这一节是缺的，info 连级别检查都过不去、warning 只经 `lastResort` 到 stderr——排查时会以为
「什么都没发生」。

**刻意不报错**：

- 重复标已读、「全部已读」提交两次 → no-op，返回 `False` / 计数归零，页面照常；
- 重复调用任何 `notify_*` → `get_or_create` 命中，不新增行、不动已读状态；
- 被撤销的提及 → 消息行直接删掉，不留「已撤销」痕迹；
- 删一条已经被删过的私信（两个标签页各按一次）→ 第二次 404，页面照常；
- 未登录时 `message_rows` / `unread_message_count` → `()` / `0`（函数自己不抛异常）。

---

## 6. 测试要点与已知限制

### 测试（`notices/tests.py`，按类看）

| 类 | 钉住什么 |
|---|---|
| `NoticeVisibilityAcceptanceTests` | 公开路由永不暴露 internal / contacts；internal 按用户组命中（任一命中即可）、别的组和无组都看不见；联系人才看 contacts；未改密成员被中间件挡回；首页只出公开通知；置顶排最前 |
| `MessageReadStateTests` | 行只含该用户可见的通知；行带类型／来自／说明／已读；联系人说明是「仅项目组联系人」；内部通知列出全部命中的组名；没有姓名时「来自」回落账号；计数只算可见未读；标已读幂等；「全部已读」只动本人可见的；删通知后行、计数、回执一起消失 |
| `EventMessageAggregationTests` | 提及行的类型／来自／说明与 `message_go` 链接；评论提及与评论通知都落到 `#comment-<pk>` 锚点（后者说明列是评论节选）；置顶最前、其余按时间混排；计数把两类相加；「全部已读」两类都清；`message_go` 别人的消息 404；不认识的 kind 跳过而不炸页 |
| `MemberHomeReminderAcceptanceTests` | 成员中心入口叫「我的消息」；有未读才有提醒条与徽标且带计数；全读完什么都不渲染；别的组的未读不触发提醒 |
| `MessageKindCoverageTests` | `KIND_CHOICES`、`_TYPE_LABELS`、`_CONTENT_BUILDERS` 三处的 kind 集合必须相等——加一类时漏掉后两处，这个测试直接红 |
| `MessagePageAcceptanceTests` | 五列（类型／标题／来自／说明／时间）；未读行 `class="unread"` 与「N 条未读」；点详情清未读标记且只留一条回执；「全部已读」的 flash 与 POST-only；没有未读时不渲染按钮；删通知后页面少一行 |
| `NoticeAdminAcceptanceTests` | 后台发布记 `published_by` 与 `notices.create` 审计；internal 没用户组、public / contacts 带用户组都拒绝保存；contacts 不带组可存；成员进不了后台 |
| `DirectMessageSendTests` | 写私信那一页渲染出收件人与上限（`maxlength` 取自模型常量）；两行一起落；消息行的四个字段；（浮动窗与整页两条路都）发完回得来、外站 `next` 被忽略；超长／空正文被拒且写过的正文还在；给自己发被 flash 挡回；停用账号与匿名进不来 |
| `DirectMessageInboxTests` | 行读什么（类型／标题／来自／节选／回信对象）；发信人自己没有行；未读计数与成员中心提醒条／徽标；点开即已读且**读完还在**；详情页给全文而不是节选；主动删除连正文一起删；越权 404；非私信的消息没有私信页；没有正文的坏行跳过而不是 500；快速回信就是一条普通私信（反向送达）；发信人注销后行上不再有「快速回信」 |
| `DirectMessageEntryAcceptanceTests` | 成员资料页对别人有「私信」入口与那扇窗（`data-direct-compose` / `data-direct-dialog` / 收件人姓名），对自己的资料页两者都没有 |

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
- **私信没有「已发送」列表**：发信人看不到自己发出去的私信（要看见只能等对方回一条），
  删掉收信人那一行也就再没有别处留着它。这是本轮刻意的边界——需求里只要求收信人能读、能删、能回。
- **私信正文的上限只在表单把关**：模型字段的 `max_length` 与数据库都没有拦（PostgreSQL 的
  `text` 不限长），绕过 `DirectMessageForm` 直接调 `services.send_direct_message` 能存进超长正文
  ——与图册合计上限同一种把关方式（`accounts.services.add_gallery_images`）。
- **没有「不能给自己发」的库约束**：`DirectMessage` 上没写 `sender != recipient` 的
  `CheckConstraint`，服务层与视图各挡一次。加约束要先想清存量数据与迁移，收益也不大。
- **「快速回信」本身不标已读**：它只打开窗口，那条私信行仍旧是未读，直到点开详情页
  （或「全部已读」）。回复不等于读过——正文全文只有详情页给。
- **私信不写审计也不进后台**（理由见 §5）：出了「谁给谁发过」的争议，平台这边**没有可查的底账**，
  能查的只有收信人自己那一页。
- **浮动窗要脚本才弹**：没有脚本时那几个入口是普通链接，落到 `direct_compose` 整页表单——
  功能不缺，少的是弹窗这一层观感（`static/js/direct_compose.js` 的第一句就 return 掉了）。
- **`Message` 的六个引用没有组合约束**：哪一类消息挂哪个引用是 `services.py` 写入函数的责任
  （模型 docstring 明说）。绕过 services 直接建行能造出渲染不出来或语义错乱的消息；加新 kind 时
  三处（`KIND_CHOICES`、`_TYPE_LABELS`、`_CONTENT_BUILDERS`）必须同时改，漏掉后两处由
  `MessageKindCoverageTests` 挡下。
- **`mark_all_read` 的返回计数**是「尝试写的回执数 + 被 UPDATE 的事件消息数」，并发下可能多报
  （回执被 `ignore_conflicts` 挡掉，但计数已经算进去了）。这个数只用于日志，不影响页面。
- **`list.html` 今天只服务公开列表**：它带 `detail_namespace` / `detail_name` 两个参数、范围列直接写
  `{{ notice.scope }}`、不写已读回执——把成员侧的通知接进这一页会同时丢掉回执与范围口径。
  成员侧另有 `message_list.html`。
- **已读回执没有清理入口**：只随通知／账号级联删除，没有「清理 N 天前的回执」这类命令。

---

## 7. 由来

> 这一节只讲**当初为什么这么定**——从代码里读不出来的那部分。跨模块的口径与依赖方向在
> [`../docs/更新维护/模块与关系.md`](../docs/更新维护/模块与关系.md)。

- **为什么消息只存引用、不存副本**：行里存的是五个可空外键与已读状态，标题／链接／说明由 `notices.selectors` 现取现算——帖子改名、轮次出了新结论，消息里跟着变，不会对不上。**别把显示字段落进表**，那会让这条性质失效。
- **为什么用字符串外键**：notices 因此不在加载期依赖 `discussion` / `reviews` / `projects`；「哪一类消息挂哪个引用」不加库约束，交给写入函数。
- **为什么未读要现算**：可见通知 − 已读回执（`NoticeRead`），不物化副本——发布人删通知，成员侧自然消失，回执随 CASCADE 清掉，不留孤儿。
- **为什么私信的正文单开一张表**：消息行的规矩是「只存结构化引用与状态，可显示字段现取现算」——
  私信的正文恰恰没有别的家，别的 kind 的来源（帖子、评论、申请、轮次）都另有主人，私信没有。
  两条路：给 `Message` 加一列正文（那一列的规矩就破了，且将来每种「自带正文」的消息都要挤在这一列上），
  或者让正文自己也当一次「来源」。选了后者：`DirectMessage` 是来源，`Message` 照旧只指过去，
  「来源删除即级联删行」这条口径一个字都不用改，删除就是删来源。
- **为什么私信不写审计**：见 §5。**不写是决定，不是漏做**——只追加的表配私人往来，代价是永久留痕。
- **为什么「读完」不改消息的存亡**：已读与存在是两件事。删掉一条私信是收信人的动作（他不想再看见），
  与「读过」无关；反过来，读过就消失会让人再也找不到对方说过的话。所以删除只留一个手动入口，
  且只有收信人有（发信人那边本来就没有行）。
- **为什么回信也是一种普通私信**：回复不建新类型、不建会话表——它就是把收件人与发信人对调再发一条。
  于是未读、计数、提醒、删除全都复用同一条路，不必为「回复」再想一套状态。
- **为什么撤回了「登录 flash 与成员中心待办卡片」**：同一个数字不该有两处口径；未读统一由「我的消息」的提醒条报出。任务类消息跟着任务生命周期走（交掉／被释放／被改派即撤），历史归评审页。
