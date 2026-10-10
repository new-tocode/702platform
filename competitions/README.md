# competitions 模块

> 竞赛信息发布与项目组报名登记：`Competition` 与 `CompetitionRegistration` 两张表，
> 前台三个写入口（报名／修改／放弃）加后台补录。
> **不做审批流**（登记即生效），**不做评审**（竞赛与送审轮次之间没有外键，`review_type`
> 只是平台本地标签），也**不判「谁是联系人」**——那问 `projects.permissions`。
> 依赖它的只有两处：`core.registry` 的入口卡片与 `core.stats` 的概览计数。

**什么时候看**：改报名规则、动截止时间口径、改竞赛或报名字段、碰后台补录，或回答
「谁能报名／截止后还能不能改」时。

---

## 1. 职责与边界

| 面 | 落点 |
|---|---|
| 两张表；唯一口径 `Competition.is_registration_open` | `models.py` |
| 判定：`is_competition_manager`、`can_register_group`（薄封装，委托 `projects.permissions.can_manage_group`） | `permissions.py` |
| 写操作：`save_registration`、`withdraw_registration`（事务、审计、约束冲突翻译） | `services.py` |
| 前台表单 `CompetitionRegistrationForm` 与后台表单 `CompetitionRegistrationAdminForm` | `forms.py` |
| 四个页面入口、模板、按钮可见性（`can_manage_competitions`） | `views.py`、`urls.py`（`member/competitions/`）、`templates/competitions/`、`context_processors.py` |
| 成员中心入口卡片（key `competitions.registration`）；后台发布与补录 | `apps.py`、`admin.py` |

**明确不做**：

| 不做 | 落在哪 |
|---|---|
| 联系人／组员身份判定、「谁算管理员」 | `projects.permissions`；本模块只加业务语义名。管理员问 `core.permissions.is_admin` |
| 报名审批 | 有意不做：登记即生效，表上没有状态字段（`docs/architecture/overview.md`） |
| 竞赛与送审轮次的关联 | 没有这条链路：`ProjectSubmission.review_type` 刻意不与 `Competition` 建外键（`reviews/models.py`） |
| 文件上传／取件；概览里的开放竞赛计数 | 本模块没有任何文件字段；计数在 `core.stats.platform_overview`（局部 import `Competition`） |

**没有的模块**：没有 `selectors.py` 也没有 `panels.py`，列表页上下文直接由
`views.competition_list` 装配（`docs/development.md` §1.2 的括注也是这个口径）。代价是
`forms.py` 与 `views._member_group_map` **直接查 `ProjectGroup`**（含 `members.through`）；
项目组侧改成员结构会波及这里。

---

## 2. 关键接口与失败模式

| 入口 | 语义 | 前置条件 | 失败模式 |
|---|---|---|---|
| `permissions.is_competition_manager(user)` | 管理员或任一项目组联系人 | — | 只返回布尔；用在报名页门槛与 `can_manage_competitions` |
| `permissions.can_register_group(user, group)` | 委托 `can_manage_group`：管理员任意组，联系人限自己的组 | — | 假 → 表单在 `group` 字段报错 |
| `services.save_registration(...)` | 新建（`instance=None`）或修改；新建时 `registered_by = actor` | **调用方保证报名开放**——服务层不查截止 | `IntegrityError` → `DuplicateRegistration`；修改不改 `registered_by` |
| `services.withdraw_registration(...)` | 删除一条报名 | `is_registration_open` | 不开放 → `RegistrationClosed`，记录保留；审计 detail 在删除前取出 |
| `views.competition_list` | 列表，所有登录成员可见；联系人多看到自己可管理的报名行 | 登录 | 匿名 → 302 登录页 |
| `views.competition_register` | 报名页（GET 表单／POST 提交） | `is_competition_manager`；报名开放 | 门槛**先于取对象**：非联系人即使 pk 不存在也 403；已关闭／截止 → 302 回列表 + error；重复 → `group` 字段报错（页面 200） |
| `views.competition_registration_edit` | 修改报名 | `can_manage_group`；开放 | 非本组联系人 → 403；已截止 → 302 回列表 + error |
| `views.competition_registration_withdraw` | 放弃报名（`@require_POST`） | 同上 | 非本组 → 403；已截止 → 302 + error，**记录仍在**；GET → 405 |
| `admin.CompetitionRegistrationAdmin` | 后台补录／修改／删除 | 成员须属于项目组 | **刻意不校验截止时间**；也不查「组长在参赛成员内」 |

---

## 3. 状态与不变量

**`Competition`**：`is_open`（默认 `True`）与 `deadline` 是两个独立条件；
`is_registration_open` 是**唯一口径**——`self.is_open and timezone.now() <= self.deadline`，
两者都成立才开放，`<=` 意味着**截止那一刻仍算开放**；列表徽章据此分
「报名开放中／报名已截止／报名未开放」三种。`team_size` 是自由文本，**只作展示**
（help_text 原文：仅作展示说明，具体成员由报名时选择），人数没有任何强制校验。
`published_by` 后台只读、新建时由 `save_model` 填当前管理员；`published_at` 同样只读，取模型默认 `timezone.now`。

**`CompetitionRegistration`**：唯一约束 `(competition, group)`
（`unique_competition_group_registration`）是本模块**唯一由数据库保证**的业务规则；
`registered_by` 是首次登记人，任何修改（含后台）都不改它；`team_leader` 可空；
「成员属于项目组」「组长属于项目组且在参赛成员内」全靠表单；`members`、`remark`（≤2000）
没有数据库约束；**五个外键一律 `PROTECT`**——删发布人、登记人、组长或已报名的项目组
会被数据库挡下。

**必须成立的断言**

- **截止口径只有一处（除了一处重复表达）**：`core.stats` 的平台概览用 `is_open=True, deadline__gte=now` 把同一条判定又写了一遍（今天语义等价，都是闭端）——改 `is_registration_open` 时一并核对它。
- **截止口径只有一处**：前台三个入口、前台表单、列表徽章都问 `is_registration_open`，
  **后台刻意不问**（见 §6）。报名与修改的校验在表单 + 视图各拦一次；放弃只有一个调用方，
  校验写在 `services.withdraw_registration`——`save_registration` **自己不看截止**，
  新增前台写入口必须自带这道校验。
- **同组同赛一条**：表单查重只是提示，并发下靠唯一约束兜底（`IntegrityError` →
  `DuplicateRegistration`）；服务层没有行锁。
- **成员归属校验写了两份**：两张表单的 `clean` 各算一次 `group.members` 集合；前台多看
  一条「组长必须在参赛成员内」，后台没有。
- **审计 action 一旦发布不再改**，清单见 §5。

---

## 4. 数据流与时序

**报名**：`@login_required` → `_require_competition_manager` → 取竞赛 → 报名不开放则
302 回列表。候选组＝`manageable_group_ids(user)`，成员／组长候选＝这些组的全体成员
（跨组并集，新建时组长初值是联系人本人）。`_member_group_map` 给
`static/js/registration.js` 生成「成员 → 所属组」映射，切组时收窄两个下拉——**只是渐进
增强**，服务端 `clean` 才是权威（截止 → `can_register_group` → 是否已有同组同赛 →
成员属于组 → 组长属于组且在成员内）。`save_registration` 在事务内 create + `members.set`，
**审计写在事务外**（新建的 detail 多一个 `member_count`）；成功 302 回列表。

**修改**：先 `can_manage_group`（403）再看开放（302）；同一个 `save_registration`（带
`instance`）改 `group` / `team_leader` / `remark` 并重设 `members`，审计是
`competitions.registration.update`。

**放弃**：`can_manage_group` → 服务层复查开放 → 删除。审计 detail 的竞赛／组 id
**必须在删除前取出**（记录没了就取不到），审计行本身写在删除之后。

**后台**：`CompetitionAdmin` 照存任意 `deadline`，`published_by` 只读、新建时填当前管理员；
`CompetitionRegistrationAdminForm` 不看截止，`registered_by` 只读、新建时填当前管理员。

---

## 5. 错误处理与诊断

**领域异常只有两个**（都在 `services.py`）：`DuplicateRegistration` 由视图翻成 `group`
字段的错误（页面 200）；`RegistrationClosed` 翻成 `messages.error(str(exc))` + 302，记录保留。

| 情形 | 表现 |
|---|---|
| 匿名访问任一入口 | 302 登录页（带 `next`） |
| 非管理员／联系人访问报名页 | 403（`core.permissions.require`，event `competition.permission.denied`） |
| 非本组联系人打开修改页／放弃 | 403（视图先记 `.edit.denied` / `.withdraw.denied` 再 `raise PermissionDenied`） |
| 已关闭／已截止时打开报名页或修改页 | 302 回列表 + error（**不是** 403／404） |
| 已截止时放弃 | 302 + error，记录仍在 |
| 重复报名 | 页面 200，`group` 字段报「该项目组已经登记过这场竞赛，不能重复报名。」 |
| GET 打放弃入口；对象不存在 | 405；404 |

**审计 action**（不再改）：`competitions.create` / `.update`（`CompetitionAdmin.save_model`，
detail 有 `is_open`、`deadline`）；`competitions.registration` / `.registration.update`
（`save_registration`，detail 有 `competition_id`、`group_id`，新建多 `member_count`）；
`competitions.registration.withdraw`（无 target，记录已删）；`competitions.registration.admin_create`
/ `.admin_update`。**后台删除不写这些审计**（`delete_model` 未覆盖，走 Django 默认动作）。

**日志**：logger 名 `competitions.views` / `competitions.admin`，均带 `request_id`。
锚点：`competition.list.view`、`competition.registration.success` / `.failure`（`reason=duplicate`
或 `errors=`）/ `.rejected`（`reason=closed_or_expired`）、`.edit.denied`、`.withdraw.denied`
/ `.withdraw.rejected`、`admin.competition.save`、`admin.competition_registration.save`；
审计写入本身另记一条 `audit.record`。

---

## 6. 测试要点与已知限制

| 类 | 钉住什么 |
|---|---|
| `CompetitionAcceptanceTests` | 所有登录成员能看列表，但只有联系人看得到报名入口（入口在成员中心卡片，不在公开首页顶栏）；匿名 302；组员访问报名页 403；只能报自己的组；成员属于组、组长在组内且在参赛成员内；重复提交被拒；关闭／截止后拒绝；修改报名且 `registered_by` 不变；跨组修改 403；放弃；管理员可为任意组报名 |
| `RegistrationDeadlineAcceptanceTests` | 截止后放弃被拒且记录仍在；截止后修改被拒；开放时放弃成功——三条路同一个 `is_registration_open` |
| `AdminDeadlineOverrideAcceptanceTests` | **后台不受截止约束**：可发布 deadline 在过去的竞赛（照常保存，只是前台不开放）；可往已截止竞赛补录；可改已截止报名的备注 |

跨模块还有两处钉着本模块：`core/tests/test_registry_and_audit.py`（入口 key
`competitions.registration` 的注册与可见性）、`core/tests/test_upload_validation.py`
（`remark` 上限 2000，模型与表单一致）。

### 已知限制 / 当前不支持

- **截止时间只约束前台，后台可任意补录**：三个前台入口（报名、修改、放弃）与
  `CompetitionRegistrationForm` 都受 `is_registration_open` 约束；
  `CompetitionRegistrationAdminForm` **刻意不看它**，`deadline` 在后台也可填任意时间（含已过去）。
  已截止的竞赛要加项目组，**后台是唯一入口**——这是有意设计，`AdminDeadlineOverrideAcceptanceTests`
  就是它的护栏；谁在后台表单里补上与前台一致的截止校验，就堵掉了补录这条路。
- **后台不校验「组长是参赛成员之一」**：它只查组长属于项目组，所以后台能造出组长不在
  参赛成员内的记录。
- **`save_registration` 不查截止**，服务层也不会替你拦——新增前台写入口必须自己带校验。
- **无行锁**：重复报名靠唯一约束兜底，不是 `select_for_update`；两个请求同时报同一组同一赛，
  一个成功、另一个得到 `DuplicateRegistration`。
- **外键一律 `PROTECT`**：删账号（发布人／登记人／组长）或删已报名的项目组会被数据库挡下。
- **人数没有校验**：`team_size` 只是文本，`members` 的数量不受它约束；修改报名时可以改
  `group`（候选范围内），唯一约束会重新校验。
