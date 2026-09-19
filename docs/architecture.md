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
| 审批流程 | 竞赛报名、设备借用为登记即时生效。**加入项目组**需该项目组联系人审核；**创建项目组**需任一管理员同意；**项目书**需同行评审：先由 1 名初审人初审，通过后才按送审类型随机分配评审人（竞赛类 3 人、大创中期/结题 2 人、大创立项 1 人），全部评审人均通过方为通过，批注版项目书随通过归档 |
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
| `reviews` | 项目书同行评审（送审类型与配额、初审关卡与评审同表任务、批注版项目书、结论汇总与归档、超级评审、评审资格与可见性判定） |
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
  - is_reviewer           bool  评审资格（默认 False）
  - is_preliminary_reviewer bool 初审资格（默认 False）
  - is_super_reviewer     bool  超级评审资格（默认 False）
  - 权限口径以用户上的布尔标志表达（is_staff／is_reviewer／is_preliminary_reviewer／is_super_reviewer），不新增 role 字段；
    Django auth.Group 只用于内部通知的投递范围

Profile（User 一对一扩展）
  - user          OneToOne(User)
  - full_name     姓名（单一字段）
  - student_id    学号（唯一）
  - college       学院
  - major         专业
  - specialty     特长（自由文本，可写多项）
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

HomeSlide（首页轮播）
  - image          FK(MediaFile, 限图片)  滚动区用图，取自共享媒体库
  - title          说明文字（可空，回退到图片 caption）
  - sort_order     排序
  - is_active      是否启用
  - created_at
```

> 平台概览数字（在册成员／项目组／开放竞赛／在借设备）由 `core/stats.py` 提供，
> 只对管理员与项目组联系人呈现，展示在成员中心；公开首页不再展示这些内部规模数据。

### 6.4 projects

```
ProjectGroup
  - name           组名
  - leader         FK(User)  项目组联系人（一个，唯一真相源）
  - members        M2M(User) 组员（保存时自动确保项目组联系人也在成员列表中）
  - description    简介
  - college        学院
  - created_at
  - updated_at

ProjectAdvisor（指导老师）
  - group          FK(ProjectGroup)
  - name           指导老师姓名（纯文本——平台没有教师账号可关联）
  - sort_order     槽位 0 / 1 / 2
  - created_at / updated_at
  - 槽位唯一约束 (group, sort_order) 加 CHECK(sort_order < 3)，两条合起来即「每组至多 3 位」；
    上限只有一处写法：projects.models.MAX_ADVISORS_PER_GROUP

GroupJoinRequest（入组申请）
  - group          FK(ProjectGroup)
  - applicant      FK(User)
  - message        申请理由
  - status         pending（待审核）| approved（已通过）| rejected（已拒绝）
  - decided_by     FK(User, 可空)  处理人
  - decided_at     处理时间
  - created_at / updated_at
  - 部分唯一约束：(group, applicant) 仅当 status=pending —— 同组同一人同时只有一条待审申请，被拒后可重新申请

GroupCreateRequest（创建项目组申请）
  - name / description    项目组名称与描述（申请时必填）
  - college               学院（选填）
  - advisor_1 / _2 / _3   指导老师三位固定槽位（选填，与 MAX_ADVISORS_PER_GROUP 一一对应）
  - applicant             FK(User)  申请人——通过后即新组的项目组联系人
  - status                pending（待审核）| approved（已通过）| rejected（已拒绝）
  - decided_by / decided_at
  - created_group         OneToOne(ProjectGroup, 可空)  通过后建成的项目组
  - created_at / updated_at
  - 部分唯一约束：(applicant) 仅当 status=pending —— 同一申请人同时只有一条待审申请，被拒后可重新申请
```

- 联系人身份**由 `ProjectGroup.leader` 计算**，不新建任何用户组存储；判定统一收敛在 `projects/permissions.py`。
- 联系人可审核入组申请、移除非联系人成员、修改项目组介绍、维护学院与指导老师、把联系人转让给组内成员（原联系人保留为普通成员）。
- **申请创建项目组**：任何登录成员（不论身份）都能在项目组页发起，申请人为项目组联系人；学院与指导老师可以先不填。审核人是**全体管理员**，任一管理员同意即视为通过——`approve_create_request` 在事务内锁行并复查状态，其余管理员随后提交同一申请只会收到「该申请已被处理」，不会建出第二个组。通过后按申请内容建立正式 `ProjectGroup`（指导老师从申请的三列槽位转成 `ProjectAdvisor` 行）并出现在项目组列表中；拒绝则申请人可修改后重交。创建申请后台只读留痕，处理入口只在项目组页。
- 学院与指导老师在同一张表单上维护：指导老师固定三行输入框，空槽位表示没有这一位，保存时按槽位顺序补齐（`projects.services.update_group_info`），因此不会撞上槽位唯一约束。学院与指导老师在项目组详情页与项目组列表页都对外展示。

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
  - review_type    送审类型，决定初审通过后需要的评审人数（REVIEWER_QUOTA）
  - message        提交说明（如“申请开题”）
  - status         preliminary_pending（初审中）| pending（评审中）| approved（已通过）| needs_revision（需修改）
  - submitted_by   FK(User)  提交人（项目组联系人）
  - submitted_at / decided_at
  - required_reviewers  由 review_type 推导；留空的旧轮次回退为 2 人
  - OPEN_STATUSES  尚未出结论的两个状态（初审中、评审中），「本轮是否还在进行」一律问它

ReviewTask（任务卡：初审一道关、评审一个评审团，两张表合并成一张）
  - submission     FK(ProjectSubmission)
  - stage          preliminary（初审）| review（评审）
  - reviewer       FK(User，资格按阶段取 STAGES[stage].qualification)
  - status         pending（待处理）| completed（已完成）| released（已释放）
                   —— 字段只存中性取值，阶段化的叫法（待初审／已初审／待评审）
                   由 ReviewTask.status_label 按 (stage, status) 给出
  - decision       approve（通过）| revise（需修改）
  - comment        意见
  - annotated_file 批注版项目书（选填；只有评审阶段会填）
  - is_override    该行来自超级评审的一票决定（只有评审阶段会有）
  - assigned_at / completed_at
  - 唯一约束：① (submission, reviewer)——一人一轮一席；② (submission) WHERE
    stage='preliminary'——每轮恰好一条初审（允许零条：升级前留下的老轮次）；
    ③ is_override=false OR stage='review'——超级评审那一票只属于评审阶段

ArchivedProposal（批注版项目书归档）
  - group        FK(ProjectGroup)
  - submission   FK(ProjectSubmission)
  - source_task  FK(ReviewTask)
  - file         批注版项目书
  - archived_at
  - 唯一约束：(source_task)，保证归档幂等

ReviewerLeave（评审人请假）
  - reviewer   FK(User，须有 is_reviewer 资格)
  - starts_at / ends_at  请假窗口（ends_at 为开区间端点）
  - reason     事由（选填）
  - created_by 首次登记人（本人或管理员）
  - created_at / updated_at
  - CheckConstraint：ends_at > starts_at
```

**送审类型与评审人数**（`REVIEWER_QUOTA` 是唯一判定点）：竞赛立项 / 竞赛省赛 / 竞赛国赛 → 3 人；大创中期 / 大创结题 → 2 人；大创立项 → 1 人。这些类型是平台内的送审标签，**不与 `competitions.Competition` 建外键关联**。

**送审流程：先过初审，再分配评审人**

- 送审**不复制项目书**：项目书只存一份在 `ProjectGroup.proposal`（doc/docx/pdf，≤20MB），初审人与评审人都从项目组详情页下载当前项目书。
- 联系人上传项目书后点「提交审核」，**必须先选送审类型**并可选填一段说明；这一轮随即以 `preliminary_pending`（初审中）落到 **1 名初审人**手里，此时**还没有任何评审任务**——送审类型决定的评审人数要等初审通过才用得上。
- 抽初审人用的是 `eligible_holders(stage="preliminary")`：只从有初审资格（`User.is_preliminary_reviewer`）、启用中、未请假、且不是提交人或本组成员的账号里随机抽 1 人；一个都没有时拒绝提交并提示。
- **提交时就先确认评审人够不够**：不够则拒绝开这一轮（提示“当前可用的评审人不足 N 人…”），预检把**本轮的初审人排除在外**——初审人不能占评审席位（后面的抽人同样排除他）。这一条守的是「不开出一轮谁也推进不了的送审」：真开出来，联系人被单轮次约束挡住、初审人也通不过，只能等管理员补资格或超级评审来收场。抽人本身仍留到初审通过时。
- 初审的结论与评审**共用同一对取值**（`approve` 通过 / `revise` 需修改）。通过 → 该轮转 `pending`，并在**同一次事务**里按送审类型随机抽齐评审人；打回 → 该轮直接 `needs_revision`，一个评审人也不分配——没准备好的项目书不占用评审人的时间。
- **本人初审通过的那一轮不会再抽到本人**（`User.is_reviewer` 与 `User.is_preliminary_reviewer` 同时具备时）。排除写在 `_eligible_pool()` 里，与「谁可以评审」的其余条件同处一地，因此抽人、容量预检与管理员改派三条路径都自动生效；只针对他初审过的那一轮，在别的轮次里他照常可以被抽为评审人。
- 初审通过时若可用评审人已不够（提交之后有人开始请假、或资格被撤销），**整次提交回滚**：结论不落库、初审任务仍是待初审，初审人可以在评审人空闲后原地重试，不必重新送审；轮次也不会停在「评审中」却无人可派。提示语会指路（“请稍后重试或联系管理员补充评审人”）——这种缺口靠等不一定能等到。
- 初审是**关卡而非评审团**：每轮恰好一条初审任务（一对一），且没有批注版项目书——它给的是理由（意见），不是稿子；批注版仍是评审人那一侧的事。
- 全部评审人都完成且都选择「通过」→ 该轮 `approved`，项目组方案通过；任一选择「需修改」→ `needs_revision`。
- 评审人可选上传一份**批注版项目书**（与项目书同格式、≤20MB），也可只填文字意见；批注版不复制原项目书。
- 该轮通过时，每位**实际上传了**批注版的评审人各产生一条 `ArchivedProposal`（真正复制文件内容），在项目组详情页的「批注版项目书」栏目可下载；未上传者不产生归档记录，`needs_revision` 轮次不归档。
- 初审结论、评审结论与意见在项目组详情页对联系人、组员、本轮初审人及被分配评审人可见；**身份一律匿名**：初审写「初审」、评审写「评审人 1/2/3」、超级评审写「超级评审」，账号只在管理员后台可见。批注文件与归档文件以不含身份的 uuid 名存储、以中性文件名下载，避免从文件名反向识别评审人。
- 项目组详情页的「方案状态」在结论为 `needs_revision` 时区分两种来路：走完评审被打回 → 指路「评审意见」；**初审直接打回**（本轮从未分配评审人）→ 指路「初审意见」，不让项目组去找不存在的评审意见。
- 修改项目书后可再次提交，产生新一轮（历史轮次保留）。**同一项目组同时只能有一个未结束的轮次**：上一轮还在「初审中」或「评审中」时都拒绝提交并提示是第几轮——判据是 `ProjectSubmission.OPEN_STATUSES`，不要再写 `status == pending`（那现在只表示「已过初审、正在评审」）。判定在锁定项目组行之后进行，该锁同时避免并发提交各自算出同一个轮次号而撞上 `(group, round)` 唯一约束。已出结论（已通过 / 需修改）的轮次不阻塞下一轮——大创中期 → 结题这类阶段推进正走这条路。
- 结论汇总在**父行 `ProjectSubmission` 的行锁**内进行：汇总要读取本轮其他评审任务，只锁自己的任务会让并发审结的双方都以为还有人待评审，从而把轮次永久卡在“评审中”。

**评审人请假**

- **评审人与初审人都可**在成员中心登记一个请假窗口（开始、结束两个时间点 + 可选事由），窗口内**不会被抽中**新的任务——初审与评审两种抽取（以及提交时的容量预检）都会在候选中排除他。界面上这块叫「初审／评审请假」；Admin 里仍是「项目评审 → 评审人请假」。
- 请假**不修改 `User.is_reviewer` / `User.is_preliminary_reviewer`**，资格始终在。「恢复」由窗口自身决定：`ends_at` 一过就自动重新可抽，**没有定时任务，也没有任何需要回滚的状态**。`ends_at` 是开区间端点（该时刻即视为在岗）。
- 请假不影响**已有的**待办任务，请假人仍可进入「评审」入口审结手头的任务。
- 一个人同时只有**一个未结束的窗口**，再次登记即修改该窗口（这既是本人提前恢复的方式，也是管理员提前/延后恢复时间的方式）；「取消请假」删除该窗口。窗口不重叠的规则由服务层保证——PostgreSQL 的索引谓词必须是 immutable，`now()` 不满足，写不成数据库约束。
- 可用评审人因请假而不够时，抽人会带上请假人数提示（“当前可用的评审人不足 N 人（另有 M 人请假）”）；抽初审人时同理（“当前没有可用的初审人（另有 M 人请假）”）。
- 管理员在 Django Admin 的「项目评审 → 评审人请假」查看全部请假，并**直接在列表上修改两个时间**（`list_editable`）以提前或延后恢复时间；改动写入审计日志（Admin 自带的 LogEntry 之外）。

**待评审提醒**

- 评审人或初审人登录时若手上有未完成的任务，登录后立刻收到一条 `messages` 提醒（amber flash）告知份数。用消息而不用跳转：登录不该悄悄改变用户原本要去的页面。
- 两种任务**分开计数、分开措辞**（“2 份项目书待初审、1 份项目书待评审”）：它们是两件事，一个数字说明不了另一个。计数由 `pending_task_summary()` 一处给出（一次查询按阶段聚合，措辞也在那里）。
- 成员中心顶部对同一批数字另给一张常驻待办卡片（`.todo`：琥珀色左边框 + 大号数字），点击直达评审队列；没有待办时整块不渲染。两种都持有时卡片写“份项目书待处理（初审 X · 评审 Y）”。
- 计数只统计 `status=pending` 的任务，且**不扣除请假**——请假不免除已经分到手的任务。
- 已被撤销相应资格者不提醒：他们进不去评审队列（`_require_reviewer` 会 403），提醒只会误导。
- 提醒发送用 `fail_silently=True`：登录**绝不能**因为提醒发不出去而失败（例如不经过中间件链的程序化登录，请求上没有 message storage）。

**更换评审人（管理员）**

- 管理员可在「项目评审 → 评审任务」的详情页把一条**待评审**的任务改派给另一位评审人。这是评审人失联、或事后发现其与本项目组有利益冲突时**唯一的补救路径**——没有它，该轮会永久停在「评审中」。
- 两道关在 Admin 里是**同一屏**（「项目评审 → 评审任务」，按「阶段」列区分）：初审是进入一轮的唯一入口，初审人失联比评审人失联更致命——整组人都被卡住，所以这条补救路径不是可选项。开放条件同样是「任务待处理 且 该轮仍停在这一关」。
- **只在「任务待处理 且 该轮尚未走出这一关」时开放，且该管理员确实持有该模型的修改权限**：逐对象的状态判断是**叠加**在普通权限判断之上，不是替代它——否则只有 `view_reviewtask`（只读观察者）的账号也能改派。逐对象判断同时决定详情页是否把「评审人」渲染成可编辑的下拉；其余记录与另外几个 reviews admin 一样全字段只读。理由：结论一旦落下，这条任务就是「谁判了什么」的记录，换人等于把结论、意见与批注文件记到别人名下。
- 由于任务仍是 `pending`、该轮的待处理任务数不变，**换人不需要重新判结论，也完全不触碰归档**。被替换者那一行是**原地改派**而不是删除（保持「每（轮次，人）恰好一条任务」——这条现在由 `(submission, reviewer)` 唯一约束背书），换人前的持有人记在审计日志里。
- 候选名单来自与抽人**同一个** `eligible_holders(stage=…)`（内部共用 `_eligible_pool()`：排除提交人、本组成员、请假中、资格不符或已停用；带 `submission` 时再排除本轮已持有任务的人——**两道关一起算**，所以本轮的初审人不会出现在评审席位的候选里）；服务层对这些规则再校验一遍，所以绕过表单的调用方也拦得住。表单会把当前持有人单独加回候选，否则下拉看不出现在是谁。
- 任务在 Admin 中**禁止新增与删除**：删除一条评审任务会**悄悄改变该轮所需的评审人数**，删除初审任务会让这一轮再也进不去评审。但**整轮可以删**——`ProjectSubmissionAdmin.get_deleted_objects` 专门豁免了这两项权限，删除的单位因此是「整轮」（Django 的级联检查会拿被级联的任务去问任务自己的 admin，不豁免就会连整轮也删不掉）。已通过并归档的轮次由 `ArchivedProposal` 的 PROTECT 挡住，删不掉；删除写审计日志（含该轮有几条评审任务、有没有初审任务）。
- 写入必须经 `reassign_task()`（`save_model` 不使用 `form.save()`），校验、加锁（沿用 submission → 任务 的锁序）与审计都在服务层。

**超级评审（一票敲定）**

- 具备 `User.is_super_reviewer` 的账号在「评审」里除自己的任务外，还能看到**全部进行中的评审**，并对其直接**通过或打回**。用途是把卡住或存在争议的轮次直接了结。
- **这一票单独敲定本轮，不走 `_settle_submission`**。那条汇总回答的是「是否每个评审人都通过了」，因此如果某个普通评审人先判了「需修改」，再走汇总就会把超级评审的决定顶回去——而那正是这条路径要做的决定。所以结论直接写入，同时统计照常不受影响。
- 打回映射为 `needs_revision`（需修改）：项目组可修改后重新送审，与三态流程、单轮次约束完全一致。
- **「进行中」包含初审中**：一轮还压在初审人手上时，超级评审照样可以一票敲定它（`override_blocker()` 判的是 `ProjectSubmission.OPEN_STATUSES`）。这是初审人失联时的另一条出路，也让这个角色不必等到评审阶段才生效。
- 敲定时，本轮仍**等待中**的任务变为 `released`（已释放）：评审任务与初审任务一视同仁——不再计入待办与提醒、不能再提交，但行保留，名单上仍看得出曾请过谁。**已完成**的任务原样保留——它们的结论是历史。
- 超级评审那一票自身记成一条 `is_override=True` 的评审任务，因此批注文件、意见文字、通过时的归档全部复用现成机制（`_archive_annotated_proposals` 会一并收走此前普通评审人已上传的批注版）。页面只显示「超级评审」，不显示账号，匿名口径不变。
- 可否行使该权由 `override_blocker()` 一处判定，它返回**不可行使的具体原因**（`None` 表示可以行使），`can_override_review()` 只是它的布尔包装：超级评审资格；轮次尚未出结论；提交人、项目组成员不得行使（利益冲突）；**已在本轮持有任务的超级评审人不得行使**（请直接提交那条任务，否则同一轮会被记两票）——初审任务同样算数，且提示语按它是否已提交分成两句（“请直接提交那一条” / “你是本轮的初审人，已经就该轮给出初审意见”），不复用一句做不到的建议。表单显隐、拒绝信息、以及队列页对「不可行使」的标注全部取自这一个函数，不另写一份判定。
- 队列页的「全部进行中」**列出全部进行中的轮次**（含初审中，看到全貌正是这个角色的意义），但对当前账号不可行使的那些会标出原因（`不可行使 · 你是本轮的提交人`），按钮也只写「查看项目书」而不是「查看项目书并决定」——不承诺做不到的事。
- 因为「已释放」不等于「待处理」，请假、待办提醒、管理员改派、单轮次约束这些机制天然把它排除在外。
- 相配套的守卫：`submit_verdict()` **非 `pending` 一律拒绝**（不写“拒绝 `completed`”）。否则被释放的人仍能提交，把任务从「已释放」翻成「已完成」——在该轮已经出结论之后改写记录。

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
| 初审人 | 每轮送审的**唯一一道前置关卡**：初审通过后才会分配评审人，打回则本轮直接结束 | **用户属性**：`User.is_preliminary_reviewer`（与评审资格相互独立；两种资格都有时，本人初审通过的那一轮不会再抽到本人做评审） |
| 超级评审 | 可看到全部进行中的评审，并对其直接通过或打回：该票单独敲定本轮，等待中的任务随即被释放 | **用户属性**：`User.is_super_reviewer`（与评审资格相互独立；只有同时具备评审资格才会被随机抽为普通评审人） |
| 管理员 | 系统管理 | `is_staff`（Django Admin）+ 自定义 `Permission` |

- 「项目组联系人」**不新建用户组存储**：身份由 `ProjectGroup.leader` 计算，判定收敛在 `projects/permissions.py`（`is_project_contact` / `is_project_member` / `can_manage_group` / `can_use_equipment` / `groups_visible_to`），其他模块复用这些函数，避免出现会漂移的副本。
- **评审资格的判定归评审应用**：`reviews/permissions.py`（`is_reviewer` / `is_preliminary_reviewer` / `is_super_reviewer` / `qualifies_for_stage` / `has_review_qualification` / `may_receive_tasks` / `has_review_claim`）。projects 与 accounts 只在函数体内局部 import 这一个模块——依赖方向因此是单向的，projects 不会再为了问一句「他是不是评审人」而去读评审的模型。
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
| 申请创建项目组 | — | ✔ | ✔ | ✔ | ✔ |
| 审核创建项目组申请（同意/拒绝） | — | — | — | — | ✔ |
| 借用设备 / 查看本人借用记录 | — | — | ✔ | ✔ | ✔ |
| 归还本人已借设备 | — | ✔ | ✔ | ✔ | ✔ |
| 报名竞赛 / 修改 / 放弃报名 | — | — | — | ✔* | ✔ |
| 审核入组申请、移除成员、转让联系人、改组介绍 | — | — | — | ✔* | ✔ |
| 进入 `/admin/` 管理后台 | — | — | — | — | ✔ |
| 发布通知/竞赛、维护设备与账号 | — | — | — | — | ✔ |

\* 项目组联系人仅能管理 `leader == user` 的项目组（对象级权限）；报名/报名修改/放弃同样限自己的组。

**评审人（`User.is_reviewer`）**：额外获得「评审」入口，只能看到分配给自己的送审；可下载项目书、在项目组详情页提交评审意见与决定，并可选附一份批注版项目书；成员中心另有「初审／评审请假」面板，可登记一段不收新任务的时间窗。手上有未完成评审任务时，登录会收到提醒，成员中心顶部也常驻一张待办卡片。项目组详情页对 staff、该组成员、本轮初审人、被分配任务（初审或评审）的账号，以及该组有未结束轮次时的超级评审可见——这几项授权是**并集**，同时具备多种资格的账号不会因为走了某一支而丢掉自己任务带来的可见性（`can_view_group`）。

**初审人（`User.is_preliminary_reviewer`）**：「评审」入口与队列对**三种资格中的任意一种**开放（`reviews/permissions.py` 的 `has_review_qualification`），但队列里各自只看到自己那一侧：初审人看到「待初审／已完成的初审／已释放的初审」，评审人看到「待评审／已完成的评审／已释放的评审」。初审人在项目组详情页拿到的是「我的初审」面板（通过 / 需修改 + 意见，没有批注版），可下载项目书；初审**通过**即让该轮进入评审并抽齐评审人，**打回**则本轮直接结束。请假窗口对初审人同样开放（面板与时长口径都叫「初审／评审请假」）。初审人身份对项目组匿名（页面上只写「初审」）。

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
| `/` | 首页：社团影像切换区（HomeSlide，同屏单帧切换）+ 最新公开公告 + 公开内容入口 |
| `/about/` | 社团简介快捷地址（读取 ContentPage slug=about；未发布时显示空状态，不返回 404） |
| `/pages/` | 更多页面：已发布的通用 ContentPage 清单（不含 slug=about，首页「了解社团」入口） |
| `/pages/<slug>/` | 通用公开内容页（仅已发布的 ContentPage 可访问，未发布 404） |
| `/awards/` | 历年获奖列表 |
| `/showcase/` | 成员风采 |
| `/notices/` | 公开公告列表（分页） |
| `/notices/<id>/` | 公告详情 |
| `/login/` `/logout/` | 登录 / 登出 |

### 10.2 成员界面（需登录）

| 路径 | 页面 | 权限 |
|---|---|---|
| `/member/` | 成员首页：身份／评审与初审资格 + 社团概览（仅管理员与联系人可见）+ 操作面板（注册表渲染） | 登录 |
| `/member/notices/` | 内部通知 + 仅联系人可见通知列表/详情 | 登录（按受众过滤） |
| `/member/profile/` | 查看/修改个人信息 | 本人 |
| `/member/password/` | 修改密码 | 本人 |
| `/member/projects/` | 项目组列表：无组员看全部可申请，组员看自己的组，联系人看全部；管理员在此审核创建申请 | 登录 |
| `/member/projects/create/` | 申请创建项目组（名称与描述必填，申请人即项目组联系人） | 登录 |
| `/member/projects/create/requests/<req>/<action>/` | 同意/拒绝创建项目组申请（POST）；任一管理员同意即通过 | 管理员 |
| `/member/projects/<id>/apply/` | 申请加入项目组 | 登录且非该组成员 |
| `/member/projects/<id>/manage/` | 管理组：审核申请、移除成员、转让联系人、改组介绍与学院/指导老师 | 该组联系人/管理员 |
| `/member/projects/<id>/manage/requests/<req>/<action>/` | 通过/拒绝入组申请 | 该组联系人/管理员 |
| `/member/projects/<id>/manage/members/<user>/remove/` | 移除组员 | 该组联系人/管理员 |
| `/member/projects/<id>/manage/proposal/` | 上传 / 更新项目书（doc/docx/pdf） | 该组联系人/管理员 |
| `/member/projects/<id>/manage/submit/` | 提交项目书审核（选送审类型 + 可选提交说明） | 该组联系人/管理员 |
| `/member/projects/<id>/` | 项目组详情：学院与指导老师、成员、项目书、批注版项目书归档、初审与评审状态及历史 | staff / 该组成员 / 本轮初审人 / 被分配评审人 |
| `/member/projects/<id>/proposal/` | 下载当前项目书 | 同上 |
| `/member/reviews/` | 我的评审队列（初审与评审各三档：待办 / 已完成 / 已释放；超级评审另有「全部进行中」） | 初审人 / 评审人 / 超级评审 |
| `/member/reviews/leave/` | 登记/修改本人「初审／评审请假」窗口（POST） | 初审人 / 评审人 |
| `/member/reviews/leave/cancel/` | 取消本人「初审／评审请假」（POST） | 初审人 / 评审人 |
| `/member/reviews/preliminary/<id>/complete/` | 提交初审意见与决定（POST）——与下一条是**同一个视图**，按任务的阶段选门槛与表单；两条路径都保留，历史链接不变 | 该任务的初审人 |
| `/member/reviews/<id>/complete/` | 提交评审意见与决定，可选附批注版项目书（POST） | 该任务的评审人 |
| `/member/reviews/override/<id>/` | 超级评审对进行中的轮次直接通过或打回（POST） | 超级评审 |
| `/member/reviews/<id>/annotated/` | 下载某条评审任务的批注版项目书 | 同上（staff / 该组成员 / 被分配评审人） |
| `/member/reviews/archive/<id>/download/` | 下载已归档的批注版项目书 | 同上 |
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
- 评审相关记录以**只读留痕**为主，四处例外：评审人请假的两个时间可在列表上直接改（`list_editable`）；待评审且该轮未判结论的评审任务可在详情页改派评审人；待初审且该轮仍在初审中的初审任务同理；**整轮送审可删除**（连同它的初审与评审任务，已归档的轮次除外）。写操作都经服务层或审计日志留痕。
- 账号后台的「权限」区发放三种资格：`is_reviewer`（评审）、`is_preliminary_reviewer`（初审）、`is_super_reviewer`（超级评审）；三者在列表页可直接筛选。
- 按需定制更友好的发布表单（本期以 Admin 为主）。

---

## 11. 关键流程

1. **登录**：管理员创建账号（初始密码，建议设为学号/工号）→ 成员首次登录 → **强制修改密码**（`must_change_password` 置 False）→ 之后可修改资料。有未完成初审或评审任务的人登录后会立刻收到一条提醒。
2. **公告分发**：管理员发布 `scope` 明确的公告 → `public` 进首页/公开列表；`internal` 按 `visible_groups` 投递；`contacts` 由 `is_project_contact` 实时投递给全部项目组联系人。
3. **入组申请**：无组员在项目组页看到全部组 → 申请加入 → 该项目组联系人在管理页通过/拒绝 → 通过即写入 `members`（被拒可重新申请）。
4. **项目书评审**：联系人上传项目书 → 提交审核、选择送审类型（决定初审通过后分配 1~3 名评审人）并可选填说明 → 先随机抽 1 名初审人（跳过正在请假者）→ 初审人下载项目书给出结论：**通过**则在同一事务里按类型随机分配评审人（跳过请假中的人，且不含本轮的初审人），**打回**则本轮直接结束，项目组修改后可重新提交（新一轮）→ 评审人下载项目书、填写意见与决定，可选附批注版项目书 → 全部评审人均通过则方案通过并归档批注版，否则需修改后再次提交。轮次若卡住或存在争议，**超级评审可一票敲定**（初审中的轮次同样可以），等待中的任务随即被释放。
5. **评审请假**：初审人或评审人在成员中心登记请假窗口（两个时间点 + 可选事由）→ 窗口内不被抽中新的初审或评审任务，已有任务不受影响 → `ends_at` 一到自动恢复，**无需人工操作或定时任务**；管理员在 Admin 查看全部请假并可直接改时间以提前/延后恢复。
6. **竞赛报名**：管理员发布竞赛（`is_open=True`）→ 项目组联系人进入竞赛页 → 只能选择自己的项目组 → 选择组内成员并指定竞赛组长（可从参赛成员中选，含本人）→ 校验截止时间、成员/组长归属和重复报名 → 提交登记 → 截止前可修改或放弃；管理员可为任意项目组登记。
7. **设备借用**：**项目组成员**查看启用设备 → 填写计划归还日期登记借用 → 事务锁定设备并扣减可借数量 → 成员或管理员登记归还 → 状态更新为 `returned` 并在同一事务回补数量；无审批流。
8. **密码找回**：无自助找回，成员忘密码 → 管理员在 Admin 中重置。
9. **媒体上传**：管理员在 Admin 上传图片/视频 → 存入媒体库（MediaFile）→ 由简介、获奖、风采、通知等内容模型引用并公开展示；Markdown 正文经白名单过滤，Django 与 Nginx 双重限制大小与类型。

---

## 12. 后续可选项

以下能力已落地，不再列为待办：账号与强制改密、通知可见性、公开展示与媒体库、项目组与联系人、竞赛报名、设备借用、项目书同行评审（含初审关卡）、操作入口注册表、审计日志、生产部署工件。

可选的后续扩展：

- **视频转码与容量**：当前直传 MP4 不转码；视频量大时引入 ffmpeg 转码/多码率或切对象存储。
- **媒体大小上限**：图片 ≤10MB、视频 ≤500MB 为默认值，可按服务器带宽/磁盘调整。
- **站内消息 / 提醒**：报名成功、设备到期、评审结果等提醒（可用简单站内消息实现）。
- **DRF API**：已预留给小程序/校园系统对接，可按需开放只读接口。
- **可信代理与真实来源 IP**：审计日志经 Nginx 后来源 IP 记为 `127.0.0.1`，需要时可增加可信代理链配置。

