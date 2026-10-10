# 术语表

> 同一个词在所有文档与代码里必须是同一个意思。新概念随手加一行——这张表的价值全在「一直是对的」。

**什么时候看**：读任何一篇文档或代码之前；给新东西定名之前。

---

## 身份与角色

| 术语 | 含义 |
|---|---|
| 访客 | 未登录的访问者，只能看公开门户 |
| 成员 | 已登录、`is_active=True` **且已完成首次改密**的账号。改密之前除改密页外什么都进不去 |
| 无组员 / 组员 | 是否属于至少一个项目组（`projects.permissions.is_project_member`）。**只影响借设备这类「成员才有」的入口**——项目组列表对两者一视同仁（登录即可见全部） |
| 项目组联系人 | 某个项目组的 `leader`。**对象级、计算得出**，不存用户组：想改归属得去项目组页，没有「分配联系人」这个动作 |
| 评审人 | `User.is_reviewer`。可被抽为评审人，提交评审意见与批注版项目书 |
| 初审人 | `User.is_preliminary_reviewer`。每轮送审的**唯一一道前置关卡**，与评审资格相互独立 |
| 超级评审 | `User.is_super_reviewer`。可对进行中的轮次一票敲定 |
| 管理员 | `is_staff` 或 `is_superuser`——一律问 `core.permissions.is_admin`，不写 `user.is_staff`。能进 `/admin/`，也能进「评审」页（不需要评审资格） |
| 超级管理员 | Django `is_superuser`。平台里唯一**把它当作独立于 `is_staff` 的资格**来用的地方是前端创建／删除社团空间板块；别处出现 `is_superuser` 都是「管理员含超级用户」的意思（判定仍走 `is_admin`） |
| 用户组 | Django `auth.Group`。**只用于内部通知的投递范围，不是身份**，也不进身份目录 |

身份按**来源**分两种作用域：`GLOBAL`（管理员授予，后台可批量改）与 `OBJECT`（业务动作产生，名册只读、不给分配入口）。见 [architecture/permissions.md](architecture/permissions.md)。

## 项目组与评审

| 术语 | 含义 |
|---|---|
| 项目组 | `ProjectGroup`。成员经入组审批产生；联系人由 `leader` 计算 |
| 指导老师 | `ProjectAdvisor`，纯文本姓名（平台没有教师账号可关联）。每组至多 3 位，槽位 0/1/2 |
| 送审 / 轮次 | 一次「提交项目书送审」= 一条 `ProjectSubmission`，`round` 在组内唯一。**同一项目组同时只能有一个未结束的轮次** |
| 送审类型 | `review_type`：竞赛立项／竞赛省赛／竞赛国赛／大创中期／大创结题／大创立项。它只决定配额，**不与 `Competition` 建外键关联** |
| 配额 | `REVIEWER_QUOTA`：竞赛类 3 人、大创中期·结题 2 人、大创立项 1 人。唯一判定点 |
| 初审 | `stage=preliminary`。每轮恰好一条任务、一对一；给的是理由（意见），不是稿子（没有批注版） |
| 评审 | `stage=review`。初审通过后在同一次事务里按配额随机抽齐 |
| 通过 / 需修改 | 结论的两种取值（`approve` / `revise`）——初审与评审**共用同一对取值** |
| 已释放 | 任务状态 `released`：一轮被一票敲定后，仍等待的任务不再计入待办、不能再提交，但行保留（名单上仍看得出曾请过谁） |
| 改派 | 管理员把「待处理且该轮尚未走出这一关」的任务换人。评审人失联时**唯一的补救路径** |
| 一票敲定 | 超级评审对进行中的轮次（含初审中）直接通过或打回，**单独敲定本轮**，不走评审汇总 |
| 接单开关 | 初审人／评审人对自己那一类任务的接收开关（`User.receives_preliminary_tasks` / `receives_review_tasks`，默认开）。关掉后不被抽中、不进改派候选；**与资格是两回事**——资格是管理员授予的「能不能做」，开关是本人在的「现在做不做」。手上有未完成的任务时关不掉。旧机制是「请假窗口」（两个时间点 + 到点自动恢复），已整体删除 |
| 批注版 | 评审人随结论上传的项目书（选填），格式与项目书同、≤20 MB |
| 归档版 | 轮次通过时把实际收到的批注版复制成的 `ArchivedProposal`；`(source_task)` 唯一约束保证归档幂等 |
| 匿名口径 | 页面上初审写「初审」、评审写「评审人 1/2/3」、超级评审写「超级评审」，账号只在后台可见；批注版与归档版的**文件名也不含身份** |

## 通知与消息

| 术语 | 含义 |
|---|---|
| 公告 | `Notice`。三种可见范围：`public` 公开／`internal` 按用户组／`contacts` 仅项目组联系人 |
| 我的消息 | 成员中心的消息页。两类来源混排：**广播型**（公告，未读 = 可见通知 − 已读回执）与**事件型**（`Message`，一行一个收件人） |
| 事件型消息 / kind | 八个：@ 提及、初审任务、评审任务、评审结果、入组申请、入组结果、建组申请、建组结果（`Message.KIND_CHOICES`）；来源删除即级联删行 |
| 已读回执 | `NoticeRead`。进详情即写、幂等，唯一约束 `(user, notice)`，通知删除时一并清掉 |
| 提及 | 正文里的 `@姓名`。服务端解析（`discussion/mentions.py`）才是权威，前端补全只是渐进增强 |

## 文件与上传

| 术语 | 含义 |
|---|---|
| 公开件 | 落在 `mediafiles/`，由 Nginx 的 `/media/` 直出（媒体库配图——它本来就对匿名访客开放） |
| 受保护件 | 落在 `protected_media/`，**刻意不在 `mediafiles/` 之下**，没有任何 HTTP 路径能直接取到；项目书、批注版、归档版、帖子图、头像、个人图册都属这一类 |
| 取件口 | 受保护件的下载视图（`accounts:avatar_file`、`projects:group_proposal_download`、`reviews:annotated` 等），一律 `@login_required` + 视图内权限判定 |
| 落盘名 | 受保护件在磁盘上的文件名，统一换成 uuid（`core/storage.py`）——原文件名会带人名、组名，而它会跟着文件走进备份、运维的 `ls` 与下载头 |
| 指纹 / SHA-256 | 每个上传件落盘时算一份内容指纹存进记录（`core/hashing.py`，七个文件字段都接了）。**项目书、批注版、归档版**取件时另随 `Content-Digest` 与 `X-Checksum-SHA256` 两个响应头送出；头像、图册、帖子图刻意不发这两个头（图片类不在页面上展示校验值）。防的是「文件在传递途中被换掉」，不是入侵 |

## 代码结构与约定

| 术语 | 含义 |
|---|---|
| 分层约定 | `models` / `permissions` / `services` / `selectors` / `forms` / `views` / `panels` / `admin` 各自放什么，见 [development.md](development.md) 的 §1.2 |
| 判定点 | 「谁能做什么」的唯一实现处（`permissions.py`，或 `notices/visibility.py` 这类单点模块）。视图、模板、`panels` 都来问它，不各写一份会漂移的副本 |
| 视图门槛 | `core.permissions.require(request, predicate, event, **fields)`：判定 → 不通过就**记一条警告日志**（`event` 是日志前缀）并抛 `PermissionDenied`（403）。它**不写审计**（审计记的是写操作与登录锁定这类安全事件，被拒绝的请求不在其中） |
| 操作入口注册表 | `core/registry.py`。成员中心的入口卡片由注册表按登录／改密／权限／自定义条件过滤后生成 |
| 身份目录 | `core/roles.py`。登记「有哪些身份、各自叫什么、从哪来」；判定仍归各应用 `permissions`，授予仍归 `services`，目录不重复这两件事 |
| 领域异常 | 服务层抛出的业务错误（如 `ReviewError`），由视图翻译成 `messages` 文案；服务层不写用户可见文案 |
| 审计 action | `core.audit.record_audit` 的 `action` 字符串（如 `accounts.qualification.grant`）。**一旦发布就不再改**，历史记录要保持连续 |
| 状态机 / `transition()` | `reviews/lifecycle.py` 里轮次状态的**唯一写入点**；状态怎么变只在这一处 |
| `panels` | 页面上下文的装配入口（`reviews.panels`、`notices.panels`）。判定与取数都委托出去，它自己不算 |

## 双语与地址

| 术语 | 含义 |
|---|---|
| 源语言 | 中文。模板与代码里写的 msgid 本身就是中文，所以中文不需要翻译文件 |
| 地址即语言 | 中文地址不带前缀，英文走 `/en/` 前缀；与浏览器语言、Cookie 无关。后台 `/admin/` 不在双语范围内 |
| 用户内容 | 人录入的内容（通知正文、帖子、评论、资料）。**只翻译界面，不翻译用户内容** |
| 惰性译文 | `gettext_lazy` 拿到的代理。**不要在模块／类体里给它插值**（那会在导入时定型），要插值用 `format_lazy` |

## 单位与格式约定

| 约定 | 口径 |
|---|---|
| 文件大小 | 文档与界面一律写 **MB**，代码按 `1024 × 1024` 字节算（`media/validators.py`、`accounts/validators.py` 等），也就是通常说的 MiB。**不要再引入 MiB 的写法**，否则同一个上限会出现两个数字 |
| 时间 | 存储与显示统一 `Asia/Shanghai`（`DJANGO_TIME_ZONE`）。**时间窗的端点逐个看清，别记「一律」**：竞赛报名截止是**闭端**（`now() <= deadline`，截止那一刻仍可报名）。（评审请假那种两端点的时间窗已经删掉，现在是接单开关，没有时间语义。） |
| 文本长度 | 成员可自由填写的长文本都有上限，清单见 [development.md](development.md) §3.3（`core.tests.test_upload_validation.UserSuppliedTextLimitAcceptanceTests` 逐项核对） |
| 主键 | 一律数据库自增整数；地址里的 `<id>` 就是这个值 |

## 缩写

| 缩写 | 全称 / 含义 |
|---|---|
| DRF | Django REST Framework。**已从依赖中移除**（曾是「为后续 API 预留」的空依赖）；当前的对外接口面只有页面路由 |
| pg_trgm | PostgreSQL 的三元组相似度扩展，历年获奖判重用它（迁移 `content.0004_pg_trgm`） |
| CSRF / XSS | 跨站请求伪造／跨站脚本，见 [architecture/security.md](architecture/security.md) |
| HSTS | HTTP 严格传输安全。生产上默认关闭，开启的前置条件见 [deploy.md](deploy.md) |

---

**加新术语的规矩**：先问它是不是已经有一个名字（同一个东西两个叫法比没有术语表更糟）；再问代码里它叫什么、写进「含义」列时对准代码里的那个词；最后在用到它的文档里链回本表，而不是各写一遍定义。
