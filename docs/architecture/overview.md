# 1. 设计说明（SDD）总纲

> 平台是什么、给谁用、**质量目标与验收场景**、按哪些**设计视角**看、模块怎么划分与谁依赖谁。
> 详细设计在按 app 分的各篇与各 app 的 `README.md` 里，这一篇只给上位结构、坐标与「不做什么」。

**什么时候看**：第一次接触这个项目；想知道「为什么选了 Django / 为什么不用 HTMX」；
判断一处改动该落在哪一层；或者要验收一批改动。

> 版本：v2（2026-10-10 升格为设计说明总纲；此前是「项目概述」v1，定稿于 2026-08-11）
> 状态：作为后续开发的依据文档

**本项目不设需求编号。** 需求随迭代长，编号会先烂掉——所以设计视角与质量场景一律直接
指向**代码坐标**（模块路径、公开函数、路由名），而不是 `REQ-xxx`。向上追溯靠这一篇与各
app 的 README，向下落点靠代码坐标。

---

## 1. 系统与范围

面向竞赛社团的轻量管理平台，部署于单台服务器。以成员视角为核心：

- **公开门户**：访客无需登录即可浏览社团简介、历年获奖、成员风采、公开公告。
- **成员系统**：登录后进入成员界面，查看内部通知、个人信息、项目组、竞赛报名、设备借用及社团空间等功能。
- **管理后台**：管理员发布公开/内部通知、发布竞赛信息、管理账号与设备、查看各类登记汇总。

**核心原则**：单体应用、模块化拆分、权限收敛到统一的一层、操作入口可插拔。

### 1.1 不做什么（每条给理由）

需求一直会变，但**被否掉的路不该被重新走一遍**——这些是有意不做，不是还没做：

| 不做 | 理由 | 出处 |
|---|---|---|
| 开放注册、自助找回密码 | 成员由管理员发放账号，忘密码找管理员重置：社团规模下这样最省事，也避免陌生人建号 | [accounts.md](accounts.md)、[flows.md](flows.md) |
| 报名审批、借用审批 | 登记即生效；加审批要引入状态机与待办，而这两件事没有争议性 | [competitions.md](competitions.md)、[equipment.md](equipment.md) |
| 为「项目组联系人」建用户组 | 对象身份由 `leader` 计算，存两份必然分叉（见 [permissions.md](permissions.md)） | [permissions.md](permissions.md) |
| 后台的**身份名册页**提供对象身份（联系人／组员）的分配入口 | 名册是只读的；改归属要去项目组页——那才是会走业务校验的路径（名册直接指定会绕过入组审批，让身份与项目组脱节） | [permissions.md](permissions.md) |
| 教师账号、把指导老师关联成用户 | 平台没有教师账号体系，指导老师是纯文本姓名 | [projects.md](projects.md) |
| 视频转码／多码率 | 直传 MP4 由 Nginx 直出并支持 Range 拖动；转码要引入 ffmpeg 或对象存储，社团规模不值当 | [discussion.md](discussion.md)、[roadmap.md](roadmap.md) |
| 前台 API（小程序／校园系统） | 当前对外只有页面路由。DRF 曾作为空依赖装过，已按「不留不用的依赖」移除 | 本文 §6、[roadmap.md](roadmap.md) |
| 引入 HTMX 与富文本编辑器组件 | 交互以整页表单提交为主；页面脚本只做渐进增强（`static/js/` 六个文件，模板不写内联**可执行**脚本）；Markdown 在 textarea 里手写、服务端渲染 | 本文 §6 |
| 后台界面的双语 | 双语只覆盖前台，`/admin/` 固定中文 | [development.md](../development.md) §3.4 |
| 审计日志记敏感信息 | 只记非敏感结构化信息，不记密码、Cookie 与完整请求体 | [core.md](core.md) |

---

## 2. 已确认的需求决策

| 决策项 | 结论 |
|---|---|
| 技术栈 | Django（服务端渲染）。曾把 DRF 作为「为后续 API 预留」的空依赖装在项目里，后按「不留不用的依赖」移除——当前没有任何 API 层 |
| 前端形态 | 服务端渲染（Django 模板）+ 少量原生 JS/CSS；没有引入 HTMX，交互走整页表单提交 |
| 审批流程 | 竞赛报名（报名／修改／放弃三件事同受 `Competition.is_registration_open` 约束，截止后都不能动）、设备借用为登记即时生效。**加入项目组**需该项目组联系人审核；**创建项目组**需任一管理员同意；**项目书**需同行评审：先由 1 名初审人初审，通过后才按送审类型随机分配评审人（竞赛类 3 人、大创中期/结题 2 人、大创立项 1 人），全部评审人均通过方为通过，批注版项目书随通过归档 |
| 账号体系 | **不开放注册**。管理员统一发放默认账号；成员自行修改个人信息与密码；管理员可重置密码 |
| 首次登录 | **强制修改初始密码**（改密通过前，除改密页外其他成员功能不可用） |
| 媒体内容 | 支持上传**大量富文本、图片、视频**，用于公开页、通知、成员风采等场景 |
| 公开页面 | 需要「社团简介、历年获奖、成员风采」等展示栏目 |
| 界面语言 | 前台**中英双语**：中文为源语言（不带前缀），英文走 `/en/` 前缀，地址即语言；只翻译界面，人录入的内容（通知正文、板块中英文名称、帖子与评论等）不自动翻译，后台 `/admin/` 不在双语范围内 |
| 部署方式 | 由用户在服务器自行安装，架构设计不依赖部署细节 |

---

## 3. 质量目标

按「这个平台最怕什么坏」排序，前五个。它们是取舍时的裁判——两处设计冲突时，让位给排在前面的。

1. **权限判定只有一个答案。** 「谁能做什么」写在 `permissions.py`（或 `notices/visibility.py` 这类单点模块），视图门槛走 `core.permissions.require`，「谁算管理员」只问 `is_admin`。*为什么排第一*：这里管的是实名身份与评审结论，判定分叉就是越权口子，而且分叉了从页面上看不出来。*实情*：新代码按这条写；另有若干处**历史写法**——视图自己 `logger.warning` + `raise PermissionDenied`（效果相同、样板重复），以及 `discussion` 的建／删板块判定直接读 `is_superuser`。审计门槛时别只 grep `require(`。
2. **受保护件取不到就是取不到。** 项目书、批注版、归档版、头像、图册、帖子图落 `protected_media/`（刻意不在 `mediafiles/` 之下），没有任何 HTTP 路径能直接命中，取件一律经视图判定，落盘名换 uuid。*为什么*：这些文件的可见性由业务规则决定，而 Nginx 直出目录没有规则——一条拼出来的路径就能绕过全部判定。
3. **评审的结论不可改写、身份不泄漏。** 结论落定后不覆盖（改派是**原地换人**并留审计），匿名口径不许从页面、文件名或下载头里漏出去。*为什么*：结论决定项目组能否立项／结题；匿名是评审人敢说真话的前提。
4. **发得出去，也退得回来。** 任何一版代码与当版数据库兼容（删列不与依赖它的功能同版发布），发布前先备份、门禁不过即中止，回滚有明确步骤。*为什么*：单台服务器、没有灰度、出问题时维护者多半不在现场。
5. **测试是「做完了」的判据。** `check` + `makemigrations --check --dry-run` + `test` 三项全绿才算做完（见 [development.md](../development.md) §5）。*为什么*：这套用例是代码里唯一能自动回答「有没有改坏」的东西——而且它跑得快是配置出来的，不是碰巧（测试时换 MD5 口令哈希，见 §5 那一节）。

## 4. 质量场景（来源／刺激 → 期望响应 → 度量）

质量目标怎么算达成，看下面这些**可复现**的场景。每一行的度量都能当场跑出来，不是形容词。

| 场景（谁 → 做什么） | 期望响应 | 度量与验收 |
|---|---|---|
| 登录成员 → 直接请求不属于自己可见范围的项目书／批注版／归档版地址 | **403**，响应体不含文件 | `can_view_group` 在视图层拦下（`projects.views.group_proposal_download`、`reviews.views._require_group_visibility`）；受保护件不在 Nginx 的任何 `location` 里（[deploy.md](../deploy.md) §3.5 的 curl 验证） |
| 任何上传 → 几十字节的「解压炸弹」或超出上限的文件 | 当场拒绝、不落盘、不 500 | `core/uploads.py` 接住 `DecompressionBombError`；各上限用例（`core.tests` 的上传校验） |
| 两个管理员 → 同时同意同一条建组申请 | 只建成一个组，另一次收到「该申请已被处理」 | `projects.services.approve_create_request` 在事务内锁申请行并复查状态（[projects.md](projects.md)）；**注意**：现有用例覆盖的是顺序第二次提交，真并发没有用例 |
| 评审人 → 想从页面、文件名或下载头认出同行 | 认不出 | 落盘 uuid、下载用中性文件名、页面只渲染「评审人 N」（[reviews.md](reviews.md)） |
| 成员 → 下载项目书后自己核对 | 页面折叠处的 SHA-256 与响应头一致 | 三处下载（项目书／批注版／归档版）都带 `X-Checksum-SHA256`（[core.md](core.md)） |
| 开发 → 新增一句界面文案却忘了跑 `makemessages` | 兜底测试变红 | `manage.py test core.tests.test_interface_translation.InterfaceTranslationAcceptanceTests` |
| 成员 → 提交超长文本 | 表单给出友好报错，模型兜住脚本写入 | `manage.py test core.tests.test_upload_validation.UserSuppliedTextLimitAcceptanceTests` 逐项核对上限表 |
| 发布后发现坏 → 回滚 | 代码退到上一个 tag、库按发布前那份备份恢复 | [deploy.md](../deploy.md) §3 的回滚步骤 + 破坏性迁移纪律 |

> **拒绝的口径有两种，别改串**：**按对象判可见性**的取件（项目书／批注版／归档版／帖子图）
> 越权一律 **403**（`core.permissions.require` 与视图里的 `PermissionDenied`）；**通知详情**的
> 越权一律 **404**（可见性过滤直接把它们从查询集里拿掉，见 [notices.md](notices.md)）。
> 还有第三类：头像与图册只要求登录、不设对象级权限（别人的图按 `profile=` 过滤，取不到就是 404），
> 匿名则一律 302 去登录页。动某一条判据之前，先看清它属于哪一类。

## 5. 设计视角

干系人关心什么 → 看哪个视角 → 落到哪些代码。这一节是它们的目录。

「代码落点」列给的是**典型位置**：各 app 按需长出额外模块（`media` 只有 `models`／`validators`，
`core` 没有 `urls`／`views`），完整清单看各 app 的 `README.md`——模块说明正从本目录逐篇搬过去，
搬迁进度见 [README.md](README.md)。

| 视角 | 回应谁的关注点 | 在哪看 | 代码落点 |
|---|---|---|---|
| 系统与范围 | 新接手的人：这是什么、边界在哪 | 本文 §1–§2、根 [README](../../README.md) | — |
| 分层与依赖方向 | 要加代码的人：这一处该写在哪一层 | [development.md](../development.md) §1.2、本文 §8 | 各 app 的 `models` / `permissions` / `services` / `selectors` / `views` |
| 数据模型 | 要改表的人 | 各 app 的 `README.md`（详细设计） | `*/models.py` |
| 权限与角色 | 被问「这个功能谁能用」 | [permissions.md](permissions.md) | `*/permissions.py`、`core/permissions.py`、`notices/visibility.py` |
| 接口与路由 | 找地址、加页面的人 | [routes.md](routes.md) | `*/urls.py`、`*/views.py` |
| 关键流程与时序 | 想快速理解一个功能怎么走完 | [flows.md](flows.md) | 各 app 的 `services.py` |
| 状态与并发 | 改评审规则的人 | [reviews.md](reviews.md)、[core.md](core.md) | `reviews/lifecycle.py`、各 `services.py` 的行锁 |
| 安全 | 做安全相关改动的人 | [security.md](security.md) | `core/uploads.py`、`core/storage.py`、`config/middleware.py` |
| 双语与本地化 | 加文案的人 | [development.md](../development.md) §3.4 | `locale/`、`gettext` |
| 部署与运行形态 | 上线与运维的人 | [deploy.md](../deploy.md) | `deploy/*.sh`、systemd／Nginx 模板 |
| 质量目标与场景 | 验收一批改动的人 | 本文 §3–§4 | [development.md](../development.md) §5 的验收要点表 |

---

## 6. 技术栈

- **后端**：Python 3 + Django（依赖清单见 [development.md](../development.md) §2）
- **数据库**：PostgreSQL（Django 5.2 要求 ≥14；本地与生产均使用 PostgreSQL，经 `DJANGO_DB_*` 环境变量配置）
- **前端**：Django 模板（服务端渲染）+ 少量原生 JS/CSS。**没有引入 HTMX**：交互以整页表单提交为主，页面脚本只做渐进增强——`static/js/` 下六个文件（导航、@ 补全、长帖折叠、报名下拉过滤、图册、获奖勾选），由需要它的模板各自引用，模板里不写内联脚本
- **认证**：Django 内置 Session 认证 + 权限系统（Group / Permission）
- **认证模型**：自定义 User（继承 AbstractUser，除 `must_change_password` 外还有 `is_reviewer`／`is_preliminary_reviewer`／`is_super_reviewer` 三个资格字段），绿场项目直接以 `AUTH_USER_MODEL` 一步到位
- **富文本编辑**：Markdown + 服务端渲染 + `bleach` 白名单过滤，图片/视频经上传组件引用。**没有引入编辑器组件**（如 EasyMDE）：正文在后台的 textarea 里手写 Markdown，前台按 Markdown 渲染并过滤
- **媒体存储**：本地 MEDIA 目录起步（FileField 抽象，后续可经 `django-storages` 平滑切换 OSS/S3）
- **媒体校验**：Pillow 校验图片真实格式；视频校验 MP4/WebM 文件签名，统一限制扩展名、MIME 和大小
- **视频**：直传 MP4（H.264）/ WebM，由 Nginx 直接静态服务（含 Range 支持），本期不做服务端转码
- **管理后台**：Django Admin（起步阶段直接复用，按需定制）

**选型理由**：管理型 CRUD + 角色权限系统是 Django 的主场；内置 Admin、认证、权限、ORM、迁移工具；单进程部署简单。

---

## 7. 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                        客户端（浏览器）                        │
│     匿名访客           登录成员          管理员/项目组联系人          │
└───────────────┬─────────────────────────────────────────────┘
                │ HTTP/HTTPS
┌───────────────▼─────────────────────────────────────────────┐
│                      Django（单体应用）                       │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│  │ accounts │  │ notices  │  │ projects │  │competition│    │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│  │equipment │  │ content  │  │discussion│  │   core   │     │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘     │
│                                                              │
│  模板层（渲染） / 权限中间件 / 操作入口注册表 / 身份目录           │
└───────────────┬─────────────────────────────────────────────┘
                │ ORM
        ┌───────▼────────┐        ┌────────────────────┐
        │    数据库       │        │ 媒体/静态文件        │
        │  (PostgreSQL)  │        │  (上传图片等)        │
        └────────────────┘        └────────────────────┘
```

- **渲染策略**：服务端渲染。公开页、成员界面、管理后台均由 Django 模板渲染；表单提交走整页跳转。页面脚本只有渐进增强那六个（见 §6），且集中在 `static/js/`——模板里不写内联的**可执行**脚本（`|json_script` 渲染出的 `application/json` 数据块不算，它不执行）。
- **当前没有 API 层**：对外只有页面路由（见 [routes.md](routes.md)），没有任何 serializer／viewset／APIView。曾把 DRF 作为「面向未来的 API」空装着，已按「不留不用的依赖」移除；真要开放 API（小程序 / App / 对接校园系统），先引入依赖，再把接口登记进接口规格。
- **数据来源唯一**：权限判断一律在视图层完成，模板只做展示层的隐藏/显示（双层防护，见 [security.md](security.md)）。

---

## 8. 模块划分与依赖方向

| App | 职责 |
|---|---|
| `accounts` | 用户、角色分组、个人资料（学号/专业/联系方式/头像/个人简介/个人图册）、密码管理 |
| `notices` | 公告/新闻，按 `scope` 区分公开与内部可见范围 |
| `discussion` | 社团空间：板块、帖子、评论、成员目录；作者/管理员/超级管理员权限分层 |
| `content` | 公开展示页：社团简介、历年获奖、成员风采 |
| `projects` | 项目组（项目组联系人、成员） |
| `competitions` | 竞赛信息发布 + 项目组联系人报名登记 |
| `equipment` | 设备台账 + 借用登记（借/还状态） |
| `reviews` | 项目书同行评审（送审类型与配额、初审关卡与评审同表任务、批注版项目书、结论汇总与归档、超级评审、评审资格与可见性判定） |
| `media` | 媒体库：图片/视频统一上传、校验、引用 |
| `core` | 公共工具、跨应用权限口径（`is_admin`／视图门槛 `require`）、操作入口注册表、身份目录、审计日志 |

每个新业务模块 = 新增一个 Django app + 注册操作入口，主面板代码无需改动（见 [core.md](core.md)）。

### 8.1 依赖方向

- **跨应用只走公开面**：只经对方的 `permissions` / `services` / `selectors` 公开函数，不直接查对方的模型（模型层外键除外）；需要打断加载期依赖时用函数内局部 import，并写清理由。
- **方向是单向的**：`projects` 与 `accounts` 会在函数体内局部 import `reviews.permissions` 问「他是不是评审人」，反过来不存在；`projects` 与 `reviews` 之间原本有一处双向 import，随着 `reviews` 改问 `core.permissions.is_admin` 而消失。
- **`core` 是横向的**：任何 app 都可以依赖它（操作入口注册表 `core/registry.py`、身份目录 `core/roles.py`、审计 `core/audit.py`、上传校验 `core/uploads.py`）。反过来，`core` **不在加载期**依赖业务 app；`core/stats.py` 会在函数体内 import 业务模型与判定——那是刻意的运行期依赖。
- 每个 app 内部的模块分工（`models` / `permissions` / `services` / `selectors` / `forms` / `views` / `panels`）见 [development.md](../development.md) §1.2。

---
