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
| 审批流程 | **无审批，纯登记**。提交即生效，管理员只负责查看汇总与维护数据 |
| 账号体系 | **不开放注册**。管理员统一发放默认账号；成员自行修改个人信息与密码；管理员可重置密码 |
| 首次登录 | **强制修改初始密码**（改密通过前，除改密页外其他成员功能不可用） |
| 媒体内容 | 支持上传**大量富文本、图片、视频**，用于公开页、通知、成员风采等场景 |
| 公开页面 | 需要「社团简介、历年获奖、成员风采」等展示栏目 |
| 部署方式 | 由用户在服务器自行安装，架构设计不依赖部署细节（ORM 屏蔽 SQLite/PostgreSQL 差异） |

---

## 3. 技术栈

- **后端**：Python 3 + Django + DRF
- **数据库**：Django ORM 抽象（开发默认 SQLite，可平滑切换 PostgreSQL）
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
│     匿名访客           登录成员          管理员/组长          │
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
        │  (SQLite/PG)   │        │  (上传图片等)        │
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
| `projects` | 项目组（组长、成员） |
| `competitions` | 竞赛信息发布 + 组长报名登记 |
| `equipment` | 设备台账 + 借用登记（借/还状态） |
| `media` | 媒体库：图片/视频统一上传、校验、引用 |
| `core` | 公共工具、操作入口注册表、审计日志（可选） |

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
  - scope          可见范围：public（公开）| internal（内部）
  - is_pinned      是否置顶（可选）
  - visible_groups M2M(Group)  内部通知可查看的用户组（内部通知至少一个）
  - published_by   FK(User)  发布人（仅管理员）
  - published_at   发布时间
  - updated_at
  - attachments    M2M(MediaFile, blank=True)  配图/视频
```

- `scope=public`：首页与公开公告列表可见，访客无需登录；公开通知不配置用户组。
- `scope=internal`：仅登录且已完成首次改密、并且属于 `visible_groups` 任一用户组的成员可见；访客和其他用户组不可见。
- 列表查询统一走 `scope + 当前用户是否登录 + 当前用户所属用户组` 条件，详情查询也必须使用同一过滤条件。

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
  - leader         FK(User)  组长（一个）
  - members        M2M(User) 组员（保存时自动确保组长也在成员列表中）
  - description    简介
  - created_at
  - updated_at
```

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
  - registered_by  FK(User)  登记人（应为该组组长或管理员）
  - members        M2M(User) 参赛成员（从组内选择）
  - remark         备注
  - created_at
  - updated_at
  - 唯一约束：(competition, group) —— 每组每赛只登记一次
```

- 管理员发布竞赛信息；组长只能为自己负责的项目组登记报名，管理员可以为任意项目组登记（对象级权限校验，见 §7）。
- 报名成员只能从所选项目组成员中选择；项目组组长自动属于该组成员。
- 同一项目组对同一竞赛只能登记一次，由 `(competition, group)` 唯一约束保证。
- 报名必须在 `is_open=True` 且未超过 `deadline` 时提交。
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

- 无审批：成员直接登记借用；服务在数据库事务内锁定设备记录、创建借用记录并扣减 `available_count`。
- 成员仅可查看和归还自己的借用记录；管理员可查看全部记录并代归还。
- 归还操作在事务内锁定借用记录和设备，状态改为 `returned` 后才回补库存；重复归还不会重复回补。

### 6.7 core（可选）

```
AuditLog（如需审计）
  - user / action / target / detail / created_at
```

### 6.8 media（媒体库）

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
| 成员 | 登录用户，基础能力 | 任意登录用户 + `member` Group（如需） |
| 组长 | 某个项目组的 leader | **对象级**：`ProjectGroup.leader == user` |
| 管理员 | 系统管理 | `is_staff`（Django Admin）+ 自定义 `Permission` |

角色用 **Django Group + 自定义 Permission** 表达（而非 User 上的 role 字段），可组合、易扩展。

### 7.2 权限矩阵

| 能力 | 访客 | 成员 | 组长 | 管理员 |
|---|:---:|:---:|:---:|:---:|
| 浏览公开通知/展示页 | ✔ | ✔ | ✔ | ✔ |
| 登录 / 修改本人资料与密码 | — | ✔ | ✔ | ✔ |
| 浏览内部通知 | — | ✔ | ✔ | ✔ |
| 查看项目组 | — | ✔ | ✔ | ✔ |
| 借用设备登记 / 查看本人借用记录 | — | ✔ | ✔ | ✔ |
| 替本组报名竞赛 | — | — | ✔* | ✔ |
| 发布公开/内部通知 | — | — | — | ✔ |
| 发布竞赛信息 | — | — | — | ✔ |
| 维护设备、查看全部登记汇总 | — | — | — | ✔ |
| 创建/重置账号、维护项目组 | — | — | — | ✔ |

\* 组长仅能替 `leader == user` 的项目组报名（对象级权限）。

### 7.3 对象级权限（唯一的复杂度点）

Django 原生支持「组级」权限，**对象级**需自定义：

- `can_register_group(competition, user)`：校验 `user` 是该竞赛某报名组的组长，或 `user` 为管理员。
- `can_view_borrow(borrow, user)`：借用记录本人可见，管理员可见全部。
- `can_edit_profile(profile, user)`：仅本人或管理员。
- **项目组报名权限**：组长仅能为 `group.leader == user` 的项目组登记；管理员可为任意项目组登记。报名成员必须属于所选项目组。
- **通知用户组可见性**：内部通知通过 `Notice.visible_groups` 绑定 Django `Group`；用户属于任一绑定组即可查看，未命中时列表不返回、详情返回 404。Admin 表单要求内部通知至少绑定一个用户组，并禁止公开通知绑定用户组。

建议封装为通用的 mixin / helper（如 `core.permissions`），或引入 `django-guardian` 做对象权限（本期简单场景优先用自定义 helper）。

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
- **审计**：核心写操作（发布/登记/借还）建议记录操作者与时间（可在 `core.AuditLog` 落库）。

---

## 9. 操作入口可扩展机制（重点设计）

成员界面上的「操作入口」是平台的扩展点，设计为**注册表驱动**：

```
core / registry.py
  - register_entry(app_label, name, url_name, required_perm=None)
  - get_entries_for_user(user)   # 过滤出当前用户有权限的入口
```

- 各 app 在启动时（`AppConfig.ready()`）向注册表登记自己的入口，如：
  - 「查看/修改个人信息」→ `/member/profile/`，需登录
  - 「查看项目组」→ `/member/projects/`
  - 「竞赛报名」→ `/member/competitions/`，需 `组长` 或 `管理员`
  - 「设备借用」→ `/member/equipment/`
- 成员面板渲染：`{% for entry in entries %}` 生成入口卡片，**面板代码不感知具体模块**。
- **新增一个业务模块 = 新建 app + 注册入口**，主面板零改动。未来加「场地借用」「报销登记」即按此模式扩展。

---

## 10. 页面与路由

### 10.1 公开门户（无需登录）

| 路径 | 页面 |
|---|---|
| `/` | 首页：最新公开公告 + 社团简介摘要 |
| `/about/` | 社团简介快捷地址（内部读取 ContentPage slug=about） |
| `/pages/<slug>/` | 通用公开内容页（仅已发布的 ContentPage 可访问） |
| `/awards/` | 历年获奖列表 |
| `/showcase/` | 成员风采 |
| `/notices/` | 公开公告列表（分页） |
| `/notices/<id>/` | 公告详情 |
| `/login/` `/logout/` | 登录 / 登出 |

### 10.2 成员界面（需登录）

| 路径 | 页面 | 权限 |
|---|---|---|
| `/member/` | 成员首页：内部通知 + 操作面板（注册表渲染） | 登录 |
| `/member/notices/` | 内部通知列表/详情 | 登录 |
| `/member/profile/` | 查看/修改个人信息 | 本人 |
| `/member/password/` | 修改密码 | 本人 |
| `/member/projects/` | 我的/全部项目组 | 登录 |
| `/member/competitions/` | 竞赛列表 + 报名（组长入口） | 组长/管理员 |
| `/member/competitions/<id>/register/` | 为项目组登记竞赛报名 | 组长仅自己的组/管理员 |
| `/member/equipment/` | 设备列表 + 借用登记 | 登录 |
| `/member/equipment/<id>/borrow/` | 登记借用单个设备 | 登录 |
| `/member/borrows/` | 我的借用记录（管理员查看全部） | 登录 |
| `/member/borrows/<id>/return/` | 登记归还（本人或管理员） | 本人/管理员 |

### 10.3 管理后台

- 起步直接复用 Django Admin：`/admin/` 管理账号、通知、竞赛、设备、项目组、展示内容。
- 按需定制更友好的发布表单（本期以 Admin 为主）。

---

## 11. 关键流程

1. **登录**：管理员创建账号（初始密码，建议设为学号/工号）→ 成员首次登录 → **强制修改密码**（`must_change_password` 置 False）→ 之后可修改资料。
2. **公告分发**：管理员发布 `scope` 明确的公告 → 公开版进首页/公开列表，内部版进成员界面。
3. **竞赛报名**：管理员发布竞赛（`is_open=True`）→ 组长进入竞赛页 → 只能选择自己的项目组 → 选择组内成员 → 校验截止时间、成员归属和重复报名 → 提交登记；管理员可为任意项目组登记。
4. **设备借用**：成员查看启用设备 → 填写计划归还日期登记借用 → 事务锁定设备并扣减可借数量 → 成员或管理员登记归还 → 状态更新为 `returned` 并在同一事务回补数量；无审批流。
5. **密码找回**：无自助找回，成员忘密码 → 管理员在 Admin 中重置。
6. **媒体上传**：管理员在 Admin 上传图片/视频 → 存入媒体库（MediaFile）→ 由简介、获奖、风采、通知等内容模型引用并公开展示；Markdown 正文经白名单过滤，Django 与 Nginx 双重限制大小与类型。

---

## 12. 开发路线

| 阶段 | 内容 | 验收标准 |
|---|---|---|
| 1 | 项目骨架 + accounts + 登录/登出 + 角色体系 + 管理员创建账号/重置密码 | 管理员可发账号，成员可登录改密 |
| 2 | notices 公开/内部通知 + 首页 + 登录控制 | 访客与成员看到不同范围的通知 |
| 3 | content 展示页（简介/获奖/成员风采）+ media 媒体库上传（图片/视频） | 公开栏目可浏览，图片/视频可上传展示 |
| 4 | projects + competitions 发布与报名 + 组长对象级权限 | 组长可替本组报名，管理员可发布 |
| 5 | equipment 设备 + 借用登记 | 借用/归还状态流转正确 |
| 6 | 操作面板注册表机制 + 后台定制 + 安全加固（XSS/CSRF/审计） | 面板由注册表驱动，新增模块零改面板 |

---

## 13. 待定项 / 后续可选项

- ~~首次登录强制改密~~：已确认开启（见 §6.1、§11）。
- **视频容量与转码**：本期直传 MP4 不转码；若视频量大，后续引入 ffmpeg 转码/多码率或切对象存储。
- **媒体大小上限**：图片 ≤10MB、视频 ≤500MB 为默认建议值，可按服务器带宽/磁盘实际调整。
- **站内消息 / 通知提醒**：报名成功、设备到期提醒是否需要（可后续用简单站内消息实现）。
- **审计日志**：核心写操作是否需要完整审计（影响 `core.AuditLog` 是否实现）。
- **DRF API**：本期仅预留，是否提前为小程序/校园对接提供只读 API。
- **部署**：由用户自行处理（Gunicorn + Nginx + HTTPS + 备份），需保证 `requirements.txt`、环境变量配置与部署说明（README 或 docs/deploy.md）可独立完成。
