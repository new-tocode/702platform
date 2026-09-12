# 竞赛社团管理平台 —— 架构设计文档

> 版本：v1（定稿于 2026-08-11）
> 状态：作为后续开发的依据文档

---

## 1. 项目概述

面向竞赛社团的轻量管理平台，部署于单台服务器。以成员视角为核心：

- **公开门户**：访客无需登录即可浏览社团简介、历年获奖、成员风采、公开公告。
- **成员系统**：登录后进入成员界面，查看内部通知、个人信息、项目组、竞赛报名、设备借用等操作入口。
- **管理后台**：管理员发布公开/内部通知、发布竞赛信息、管理账号与设备、查看各类登记汇总。

**核心原则**：单体应用、模块化拆分、权限收敛到统一的一层、操作入口可插拔。

---

## 2. 已确认的需求决策

| 决策项 | 结论 |
|---|---|
| 技术栈 | Django + Django REST Framework（DRF 为后续 API 预留） |
| 前端形态 | 服务端渲染 + HTMX（Django 模板），DRF 暂不承担主要渲染 |
| 审批流程 | 竞赛报名、设备借用为登记即时生效。**加入项目组**需该项目组联系人审核；**项目书**需两名评审人同行评审，两人均通过方为通过 |
| 账号体系 | **不开放注册**。管理员统一发放默认账号；成员自行修改个人信息与密码；管理员可重置密码 |
| 首次登录 | **强制修改初始密码**（改密通过前，除改密页外其他成员功能不可用） |
| 媒体内容 | 支持上传**大量富文本、图片、视频**，用于公开页、通知、成员风采等场景 |
| 公开页面 | 需要「社团简介、历年获奖、成员风采」等展示栏目 |
| 部署方式 | 由用户在服务器自行安装，架构设计不依赖部署细节 |

---

## 3. 技术栈

- **后端**：Python 3 + Django + DRF
- **数据库**：PostgreSQL（Django 5.2 要求 ≥14；本地与生产均使用 PostgreSQL，经 `DJANGO_DB_*` 环境变量配置）
- **前端**：Django 模板（服务端渲染）+ HTMX（局部交互）+ 少量原生 JS/CSS
- **认证**：Django 内置 Session 认证 + 权限系统（Group / Permission）
- **认证模型**：自定义 User（继承 AbstractUser，新增 `must_change_password`），绿场项目直接以 `AUTH_USER_MODEL` 一步到位
- **富文本编辑**：Markdown（EasyMDE 编辑器）+ 服务端渲染 + `bleach` 白名单过滤，图片/视频经上传组件引用
- **媒体存储**：本地 MEDIA 目录起步（FileField 抽象，后续可经 `django-storages` 平滑切换 OSS/S3）
- **媒体校验**：Pillow 校验图片真实格式；视频校验 MP4/WebM 文件签名，统一限制扩展名、MIME 和大小
- **视频**：直传 MP4（H.264）/ WebM，由 Nginx 直接静态服务（含 Range 支持），本期不做服务端转码
- **管理后台**：Django Admin（起步阶段直接复用，按需定制）

**选型理由**：管理型 CRUD + 角色权限系统是 Django 的主场；内置 Admin、认证、权限、ORM、迁移工具；单进程部署简单。

---

## 4. 系统架构

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
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                    │
│  │equipment │  │ content  │  │   core   │                    │
│  └──────────┘  └──────────┘  └──────────┘                    │
│                                                              │
│  模板层（渲染） / HTMX 交互 / 权限中间件 / 操作入口注册表        │
└───────────────┬─────────────────────────────────────────────┘
                │ ORM
        ┌───────▼────────┐        ┌────────────────────┐
        │    数据库       │        │ 媒体/静态文件        │
        │  (PostgreSQL)  │        │  (上传图片等)        │
        └────────────────┘        └────────────────────┘
```

- **渲染策略**：服务端渲染为主。公开页、成员界面、管理后台均由 Django 模板渲染；交互（表单提交、列表局部刷新、筛选）用 HTMX 实现无刷新更新。
- **DRF 的角色**：本期不承担主要渲染，仅作为「面向未来的 API」预留（小程序 / App / 对接校园系统）。
- **数据来源唯一**：权限判断一律在视图层完成，模板只做展示层的隐藏/显示（双层防护，见 §8）。

---

## 5. 模块划分（Django app）

| App | 职责 |
|---|---|
| `accounts` | 用户、角色分组、个人资料（学号/专业/联系方式）、密码管理 |
| `notices` | 公告/新闻，按 `scope` 区分公开与内部可见范围 |
| `content` | 公开展示页：社团简介、历年获奖、成员风采 |
| `projects` | 项目组（项目组联系人、成员） |
| `competitions` | 竞赛信息发布 + 项目组联系人报名登记 |
| `equipment` | 设备台账 + 借用登记（借/还状态） |
| `reviews` | 项目书同行评审（送审、评审任务、结论汇总） |
| `media` | 媒体库：图片/视频统一上传、校验、引用 |
| `core` | 公共工具、操作入口注册表、审计日志 |

每个新业务模块 = 新增一个 Django app + 注册操作入口，主面板代码无需改动（见 §9）。

---

## 6. 数据模型设计

### 6.1 accounts

```
User（继承 AbstractUser，项目自定义，经 AUTH_USER_MODEL 生效）
  - 复用默认字段：username / password / is_staff / is_active / groups / date_joined
  - must_change_password   bool  首次登录强制改密标记（默认 True）
  - 角色通过 Group 表达，不新增 role 字段

Profile（User 一对一扩展）
  - user          OneToOne(User)
  - full_name     姓名（单一字段）
  - student_id    学号（唯一）
  - college       学院
  - major         专业
  - phone         手机号
  - contact       其他联系方式（可选）
  - created_at
```

- 管理员创建账号时设置初始密码（默认建议设为学号/工号，并在文档中提示安全改密）。
- 成员可修改 Profile 中的单一 `full_name` 姓名字段及其他个人资料与本人密码；管理员可在 Admin 中重置任意用户密码（Django 内置功能）。
- 自定义 User 仍继承 Django `AbstractUser` 的底层 `first_name` / `last_name` 数据列，但它们不再出现在任何用户界面，也不作为业务姓名使用；历史数据会在迁移中合并到 `Profile.full_name`。
- **强制改密流程**：首次登录后若 `must_change_password=True`，重定向到改密页；改密成功后置 `False`，之后才能访问其他成员功能。

### 6.2 notices

```
Notice
  - title          标题
  - content        正文（富文本/Markdown 渲染）
  - scope          可见范围：public（公开）| internal（内部）| contacts（仅联系人可见）
  - is_pinned      是否置顶（可选）
  - visible_groups M2M(Group)  内部通知可查看的用户组（仅 internal 需要，至少一个）
  - published_by   FK(User)  发布人（仅管理员）
  - published_at   发布时间
  - updated_at
  - attachments    M2M(MediaFile, blank=True)  配图/视频
```

- `scope=public`：首页与公开公告列表可见，访客无需登录；公开通知不配置用户组。
- `scope=internal`：仅登录且已完成首次改密、并且属于 `visible_groups` 任一用户组的成员可见；访客和其他用户组不可见。
- `scope=contacts`：仅登录且已是任一项目组联系人（由 `ProjectGroup.leader` 计算）的成员可见，无需配置用户组。
- 可见性判定收敛在 `notices/visibility.py` 的 `member_visible_notices(user)` 单点，列表与详情共用同一过滤条件，未授权详情返回 404。

### 6.3 content（公开展示页）

```
ContentPage（通用内容页，如「社团简介」）
  - slug           页面标识（唯一，如 about）
  - title          标题
  - content        正文（Markdown/富文本）
  - is_published   是否发布
  - updated_at
  - attachments    M2M(MediaFile, blank=True)  配图/视频

Award（历年获奖）
  - title          奖项名称
  - competition    赛事名称
  - year           年份
  - level          获奖级别（国家级/省级/校级等，自由文本）
  - winners        获奖人/团队描述
  - created_at
  - attachments    M2M(MediaFile, blank=True)  奖状/现场图/视频

Showcase（成员风采）
  - member         FK(User)  展示的成员
  - intro          简介文字
  - sort_order     排序
  - is_active      是否启用
  - photo          FK(MediaFile)  展示照片/视频
```

### 6.4 projects

```
ProjectGroup
  - name           组名
  - leader         FK(User)  项目组联系人（一个，唯一真相源）
  - members        M2M(User) 组员（保存时自动确保项目组联系人也在成员列表中）
  - description    简介
  - created_at
  - updated_at

GroupJoinRequest（入组申请）
  - group          FK(ProjectGroup)
  - applicant      FK(User)
  - message        申请理由
  - status         pending（待审核）| approved（已通过）| rejected（已拒绝）
  - decided_by     FK(User, 可空)  处理人
  - decided_at     处理时间
  - created_at / updated_at
  - 部分唯一约束：(group, applicant) 仅当 status=pending —— 同组同一人同时只有一条待审申请，被拒后可重新申请
```

- 联系人身份**由 `ProjectGroup.leader` 计算**，不新建任何用户组存储；判定统一收敛在 `projects/permissions.py`。
- 联系人可审核入组申请、移除非联系人成员、修改项目组介绍、把联系人转让给组内成员（原联系人保留为普通成员）。

### 6.5 competitions

```
Competition
  - title          竞赛名称
  - description    说明
  - deadline       报名截止时间
  - team_size      组队人数要求（如 min/max 或文本说明）
  - is_open        报名是否开放
  - published_by   FK(User)  发布人（仅管理员）
  - published_at
  - created_at
  - updated_at

CompetitionRegistration
  - competition    FK(Competition)
  - group          FK(ProjectGroup)
  - registered_by  FK(User)  登记人（审计用；应为该组项目组联系人或管理员）
  - team_leader    FK(User, 可空)  竞赛组长（为该竞赛指定的角色，从参赛成员中选，可与登记人不同）
  - members        M2M(User) 参赛成员（从组内选择）
  - remark         备注
  - created_at
  - updated_at
  - 唯一约束：(competition, group) —— 每组每赛只登记一次
```

- 管理员发布竞赛信息；项目组联系人只能为自己负责的项目组登记报名，管理员可以为任意项目组登记（对象级权限校验，见 §7）。
- 报名成员只能从所选项目组成员中选择；竞赛组长必须从所选参赛成员中指定（可为联系人本人）。
- 同一项目组对同一竞赛只能登记一次，由 `(competition, group)` 唯一约束保证。
- 报名必须在 `is_open=True` 且未超过 `deadline` 时提交。
- 报名后，联系人可在竞赛页修改报名信息或放弃报名（截止前）。
- 无审批流：登记即生效。

### 6.6 equipment

```
Equipment
  - name           设备名称
  - category       分类（文本）
  - total_count    总量
  - available_count 当前可借数量（必须 ≤ 总量，且不得小于已借出数量约束）
  - description    说明
  - is_active      是否上架
  - created_at
  - updated_at

EquipmentBorrow
  - equipment      FK(Equipment)
  - borrower       FK(User)  借用人
  - borrow_date    借用日期
  - planned_return_date  计划归还日期
  - actual_return_date   实际归还日期（已归还时必填）
  - status         borrowed（已借用）| returned（已归还）
  - remark         备注
  - created_at
  - updated_at
```

- 借用入口仅对**项目组成员**开放（未加入任何项目组的成员看不到入口、访问返回 403）。
- 无审批：成员直接登记借用；服务在数据库事务内锁定设备记录、创建借用记录并扣减 `available_count`。
- 成员仅可查看和归还自己的借用记录；管理员可查看全部记录并代归还。
- 归还不受项目组归属限制：成员被移出项目组后仍可归还既有设备，避免权限锁死。
- 归还操作在事务内锁定借用记录和设备，状态改为 `returned` 后才回补库存；重复归还不会重复回补。

### 6.7 reviews（项目书评审，期刊式同行评审）

```
ProjectSubmission（每轮送审）
  - group          FK(ProjectGroup)  项目组
  - round          轮次（组内唯一）
  - message        提交说明（如“申请开题”）
  - status         pending（评审中）| approved（已通过）| needs_revision（需修改）
  - submitted_by   FK(User)  提交人（项目组联系人）
  - submitted_at / decided_at

ReviewAssignment（评审任务）
  - submission     FK(ProjectSubmission)
  - reviewer       FK(User，须有 is_reviewer 资格)
  - status         pending（待评审）| completed（已完成）
  - decision       approve（通过）| revise（需修改）
  - comment        评审意见
  - assigned_at / completed_at
  - 唯一约束：(submission, reviewer)
```

- 送审**不复制项目书**：项目书只存一份在 `ProjectGroup.proposal`（doc/docx/pdf，≤20MB），评审人从项目组详情页下载当前项目书。
- 联系人上传项目书后点「提交审核」并附一段说明；系统**随机**从具备评审资格的用户中分配 **2 名**评审人，排除提交人本人和该项目组成员（避免利益冲突）。
- 两名评审人都完成且都选择「通过」→ 该轮 `approved`，项目组方案通过；任一选择「需修改」→ `needs_revision`。
- 评审结论与意见在项目组详情页对联系人、组员及已分配评审人可见；**评审人身份匿名**（以“评审人 1/2”展示，仅管理员在后台可见）。
- 修改项目书后可再次提交，产生新一轮（历史轮次保留）。
- 可用评审人不足两人时拒绝提交并提示。

### 6.8 core

```
AuditLog（审计日志）
  - user           FK(User)  操作者（可空，用户删除后保留记录）
  - action         操作名
  - target_type    目标类型（app_label.model_name）
  - target_id      目标 ID
  - detail         JSON  结构化非敏感信息
  - request_id     关联请求 ID
  - ip_address     请求来源 IP
  - created_at     发生时间
```

- 审计记录只能追加：Admin 只读，不允许新增、修改、删除。
- 所有 `record_audit()` 调用方只传入非敏感结构化信息，不得记录密码、Cookie 或完整请求数据。

### 6.9 media（媒体库）

```
MediaFile（统一媒体库，供各内容模型通过 M2M/FK 引用）
  - file          FileField(upload_to='uploads/%Y/%m/')
  - kind          image | video
  - caption       说明文字（可选）
  - uploader      FK(User)
  - file_size     文件大小（字节）
  - created_at
```

- **格式白名单**：图片 jpg/jpeg/png/webp/gif；视频 mp4（要求包含 `ftyp` 标识）/ webm（要求 EBML 文件头）。仅允许白名单扩展名，拒绝可执行/脚本类文件；图片还通过 Pillow 解码校验。
- **大小上限（默认建议值，可按服务器带宽/磁盘调整）**：图片 ≤10MB、视频 ≤500MB；Django 端校验，生产需同步配置 Nginx `client_max_body_size`。
- 统一媒体库的好处：公开页、通知、风采均引用同一文件；后续切换对象存储只需改一处存储配置。
- 本期**不做视频转码/多码率**：要求上传即 MP4（浏览器直放），由 Nginx 静态直出并支持 Range 拖动播放；视频量大后再引入 ffmpeg 转码或 OSS 处理。

---

## 7. 权限设计

### 7.1 角色

| 角色 | 说明 | 表达方式 |
|---|---|---|
| 访客 | 未登录，仅看公开内容 | `AnonymousUser` |
| 无项目组成员 | 已登录但未加入任何项目组 | 登录用户且 `user.project_groups` 为空 |
| 项目组成员 | 已加入至少一个项目组 | `ProjectGroup.members` 归属 |
| 项目组联系人 | 某个项目组的 leader | **对象级、计算得出**：`ProjectGroup.leader == user` |
| 评审人 | 具备评审资格、可审阅项目书 | **用户属性**：`User.is_reviewer`（管理员在后台发放） |
| 管理员 | 系统管理 | `is_staff`（Django Admin）+ 自定义 `Permission` |

- 「项目组联系人」**不新建用户组存储**：身份由 `ProjectGroup.leader` 计算，判定收敛在 `projects/permissions.py`（`is_project_contact` / `is_project_member` / `can_manage_group` / `can_use_equipment` / `groups_visible_to`），其他模块复用这些函数，避免出现会漂移的副本。
- 「组成员关系」通过 `ProjectGroup.members` 表达；「内部通知的用户组」仍是 Django `auth.Group`（`Notice.visible_groups`），两套"组"语义不同，不可混淆。

### 7.2 权限矩阵

| 能力 | 访客 | 无组员 | 组员 | 项目组联系人 | 管理员 |
|---|:---:|:---:|:---:|:---:|:---:|
| 浏览公开通知/展示页 | ✔ | ✔ | ✔ | ✔ | ✔ |
| 登录 / 修改本人资料与密码 | — | ✔ | ✔ | ✔ | ✔ |
| 浏览内部通知（按 auth 用户组） | — | ✔ | ✔ | ✔ | ✔ |
| 查看"仅联系人可见"通知 | — | — | — | ✔ | ✔ |
| 查看项目组页 | — | ✔（全部，可申请加入） | ✔（仅自己的组） | ✔（全部 + 管理自己的组） | ✔ |
| 申请加入项目组 | — | ✔ | — | — | — |
| 借用设备 / 查看本人借用记录 | — | — | ✔ | ✔ | ✔ |
| 归还本人已借设备 | — | ✔ | ✔ | ✔ | ✔ |
| 报名竞赛 / 修改 / 放弃报名 | — | — | — | ✔* | ✔ |
| 审核入组申请、移除成员、转让联系人、改组介绍 | — | — | — | ✔* | ✔ |
| 进入 `/admin/` 管理后台 | — | — | — | — | ✔ |
| 发布通知/竞赛、维护设备与账号 | — | — | — | — | ✔ |

\* 项目组联系人仅能管理 `leader == user` 的项目组（对象级权限）；报名/报名修改/放弃同样限自己的组。

**评审人（`User.is_reviewer`）**：额外获得「评审」入口，只能看到分配给自己的送审；可下载项目书、在项目组详情页提交评审意见与决定。项目组详情页对 staff、该组成员、以及被分配评审该组的评审人可见。

### 7.3 对象级权限（唯一的复杂度点）

Django 原生支持「组级」权限，**对象级**需自定义；本项目把项目组相关的判定收敛在 `projects/permissions.py`：

- `is_project_contact(user)`：是否是任一项目组的联系人（由 `leader` 计算）。
- `is_project_member(user)`：是否属于任一项目组。
- `can_manage_group(user, group)`：`is_staff` 或 `group.leader_id == user.pk`。
- `can_use_equipment(user)`：`is_staff` 或 `is_project_member(user)` —— 设备借用门槛。
- `groups_visible_to(user)`：staff/联系人→全部；有组→自己的组；无组→全部（申请模式）。
- `can_view_borrow(borrow, user)`：借用记录本人可见，管理员可见全部。
- **项目组报名权限**：`competitions.permissions.can_register_group` 委托 `can_manage_group`；报名成员与竞赛组长都必须属于所选项目组，且竞赛组长必须是参赛成员之一。
- **通知可见性**：`notices/visibility.py` 的 `member_visible_notices(user)` 单点判定 —— `internal` 走 `visible_groups`，`contacts` 走 `is_project_contact(user)`；列表与详情共用，未命中返回 404。

建议封装为通用 helper（本项目已用 `projects/permissions.py` + `projects/services.py` 落地；`competitions/permissions.py` 为薄封装）。

---

## 8. 安全设计

- **双层权限控制**：模板层按权限隐藏入口（仅影响展示）+ 视图层二次校验（真正的权限边界）。只隐藏不设防是常见漏洞。
- **CSRF**：Django 内置，HTMX 请求携带 CSRF token。
- **XSS**：模板自动转义；Markdown/富文本渲染使用安全的渲染器（如 `bleach` 白名单过滤）。
- **密码**：Django 默认 PBKDF2 哈希；`AUTH_PASSWORD_VALIDATORS` 开启强度校验。
- **上传校验**：类型白名单（图片 jpg/png/webp/gif，视频 mp4/webm）+ 大小上限（图片 ≤10MB、视频 ≤500MB）；Django 端校验 + Nginx `client_max_body_size` 双重限制；仅允许白名单扩展名，拒绝可执行/脚本类文件。
- **媒体服务**：上传落 MEDIA 目录，生产环境由 Nginx 直接静态服务（含 Range 支持便于视频拖动播放），不经过 Python 进程；视频要求 MP4(H.264)/WebM 保证浏览器直放。
- **富文本安全**：Markdown 服务端渲染后用 `bleach` 白名单过滤，禁止内联脚本；图片引用仅允许本平台 MEDIA URL（或显式白名单域名）。
- **配置安全**：`DEBUG=False`、`SECRET_KEY` 走环境变量、安全 Cookie（`SESSION_COOKIE_HTTPONLY`、生产走 HTTPS）。
- **审计**：核心写操作（发布/登记/借还/改密/改资料）通过 `core.audit.record_audit()` 写入 `AuditLog`，只记录非敏感结构化信息，后台只读查询。

---

## 9. 操作入口可扩展机制（已实现）

成员界面上的「操作入口」是平台的扩展点，已实现为 `core.registry` 注册表驱动：

```
core / registry.py
  - register_entry(key, label, description, url_name, required_permission=None,
                   visible_when=None, staff_only=False, sort_order=100)
  - get_entries_for_user(user)   # 按登录/改密状态、Django 权限、自定义条件和 URL 有效性过滤
  - OperationEntry.url          # 由 url_name 反解生成链接
```

- 各业务 app 在 `AppConfig.ready()` 向注册表登记自己的入口，例如「个人信息」「内部通知」「项目组」「竞赛信息」「设备借用」「借用记录」「审计日志」。
- 重复 key 注册是幂等的（覆盖旧定义），开发自动重载不会产生重复条目。
- 成员中心遍历 `operation_entries` 渲染入口，面板代码不感知具体模块；顶部导航不再放业务入口，仅保留公开栏目、成员中心、管理后台（staff）与退出。
- 可见性同时支持：未登录拦截、`must_change_password` 拦截、`required_permission` Django 权限、`staff_only` 管理员限制、以及 `visible_when` 自定义业务条件（如「设备借用」的 `can_use_equipment`）。
- 模板隐藏入口只影响展示；后端接口权限校验仍然独立存在，不能依赖前端隐藏。
- 新增业务模块只需在 app 注册入口，主面板模板无需改动。

---

## 10. 页面与路由

### 10.1 公开门户（无需登录）

| 路径 | 页面 |
|---|---|
| `/` | 首页：社团概览数字 + 最新公开公告 + 公开内容入口 |
| `/about/` | 社团简介快捷地址（读取 ContentPage slug=about；未发布时显示空状态，不返回 404） |
| `/pages/<slug>/` | 通用公开内容页（仅已发布的 ContentPage 可访问，未发布 404） |
| `/awards/` | 历年获奖列表 |
| `/showcase/` | 成员风采 |
| `/notices/` | 公开公告列表（分页） |
| `/notices/<id>/` | 公告详情 |
| `/login/` `/logout/` | 登录 / 登出 |

### 10.2 成员界面（需登录）

| 路径 | 页面 | 权限 |
|---|---|---|
| `/member/` | 成员首页：内部通知 + 操作面板（注册表渲染） | 登录 |
| `/member/notices/` | 内部通知 + 仅联系人可见通知列表/详情 | 登录（按受众过滤） |
| `/member/profile/` | 查看/修改个人信息 | 本人 |
| `/member/password/` | 修改密码 | 本人 |
| `/member/projects/` | 项目组列表：无组员看全部可申请，组员看自己的组，联系人看全部 | 登录 |
| `/member/projects/<id>/apply/` | 申请加入项目组 | 登录且非该组成员 |
| `/member/projects/<id>/manage/` | 管理组：审核申请、移除成员、转让联系人、改组介绍 | 该组联系人/管理员 |
| `/member/projects/<id>/manage/requests/<req>/<action>/` | 通过/拒绝入组申请 | 该组联系人/管理员 |
| `/member/projects/<id>/manage/members/<user>/remove/` | 移除组员 | 该组联系人/管理员 |
| `/member/projects/<id>/manage/proposal/` | 上传 / 更新项目书（doc/docx/pdf） | 该组联系人/管理员 |
| `/member/projects/<id>/manage/submit/` | 提交项目书审核（附提交说明） | 该组联系人/管理员 |
| `/member/projects/<id>/` | 项目组详情：成员、项目书、评审状态与历史 | staff / 该组成员 / 被分配评审人 |
| `/member/projects/<id>/proposal/` | 下载当前项目书 | 同上 |
| `/member/reviews/` | 我的评审队列（待评审 / 已完成） | 评审人 |
| `/member/reviews/<id>/complete/` | 提交评审意见与决定（POST） | 该任务的评审人 |
| `/member/competitions/` | 竞赛列表（所有登录成员可见；联系人可见报名操作） | 登录 |
| `/member/competitions/<id>/register/` | 为项目组登记竞赛报名（含竞赛组长） | 项目组联系人仅自己的组/管理员 |
| `/member/competitions/registrations/<id>/edit/` | 修改报名信息 | 该组联系人/管理员 |
| `/member/competitions/registrations/<id>/withdraw/` | 放弃报名（POST） | 该组联系人/管理员 |
| `/member/equipment/` | 设备列表 + 借用登记 | **项目组成员**/管理员 |
| `/member/equipment/<id>/borrow/` | 登记借用单个设备 | **项目组成员**/管理员 |
| `/member/borrows/` | 我的借用记录（管理员查看全部） | 登录（含已移出组者） |
| `/member/borrows/<id>/return/` | 登记归还（本人或管理员） | 本人/管理员 |

### 10.3 管理后台

- 起步直接复用 Django Admin：`/admin/` 管理账号、通知、竞赛、设备、项目组、展示内容。
- 按需定制更友好的发布表单（本期以 Admin 为主）。

---

## 11. 关键流程

1. **登录**：管理员创建账号（初始密码，建议设为学号/工号）→ 成员首次登录 → **强制修改密码**（`must_change_password` 置 False）→ 之后可修改资料。
2. **公告分发**：管理员发布 `scope` 明确的公告 → `public` 进首页/公开列表；`internal` 按 `visible_groups` 投递；`contacts` 由 `is_project_contact` 实时投递给全部项目组联系人。
3. **入组申请**：无组员在项目组页看到全部组 → 申请加入 → 该项目组联系人在管理页通过/拒绝 → 通过即写入 `members`（被拒可重新申请）。
4. **项目书评审**：联系人上传项目书 → 提交审核并附说明 → 随机分配 2 名评审人 → 评审人下载项目书、填写意见与决定 → 两人均通过则方案通过，否则需修改后可再次提交（新一轮）。
5. **竞赛报名**：管理员发布竞赛（`is_open=True`）→ 项目组联系人进入竞赛页 → 只能选择自己的项目组 → 选择组内成员并指定竞赛组长（可从参赛成员中选，含本人）→ 校验截止时间、成员/组长归属和重复报名 → 提交登记 → 截止前可修改或放弃；管理员可为任意项目组登记。
6. **设备借用**：**项目组成员**查看启用设备 → 填写计划归还日期登记借用 → 事务锁定设备并扣减可借数量 → 成员或管理员登记归还 → 状态更新为 `returned` 并在同一事务回补数量；无审批流。
7. **密码找回**：无自助找回，成员忘密码 → 管理员在 Admin 中重置。
8. **媒体上传**：管理员在 Admin 上传图片/视频 → 存入媒体库（MediaFile）→ 由简介、获奖、风采、通知等内容模型引用并公开展示；Markdown 正文经白名单过滤，Django 与 Nginx 双重限制大小与类型。

---

## 12. 后续可选项

以下能力已落地，不再列为待办：账号与强制改密、通知可见性、公开展示与媒体库、项目组与联系人、竞赛报名、设备借用、项目书同行评审、操作入口注册表、审计日志、生产部署工件。

可选的后续扩展：

- **视频转码与容量**：当前直传 MP4 不转码；视频量大时引入 ffmpeg 转码/多码率或切对象存储。
- **媒体大小上限**：图片 ≤10MB、视频 ≤500MB 为默认值，可按服务器带宽/磁盘调整。
- **站内消息 / 提醒**：报名成功、设备到期、评审结果等提醒（可用简单站内消息实现）。
- **DRF API**：已预留给小程序/校园系统对接，可按需开放只读接口。
- **可信代理与真实来源 IP**：审计日志经 Nginx 后来源 IP 记为 `127.0.0.1`，需要时可增加可信代理链配置。

