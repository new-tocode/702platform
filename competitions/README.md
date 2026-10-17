# competitions 模块

> 竞赛信息发布与项目组报名登记：`Competition` 与 `CompetitionRegistration` 两张表，
> 前台三个写入口（报名／修改／放弃）加后台补录。
> **不做审批流**（登记即生效），**不做评审**（竞赛与送审轮次之间没有外键，`review_type`
> 只是平台本地标签），也**不判「谁是联系人」**——那问 `projects.permissions`。

**什么时候看**：改报名规则、动截止时间口径、改竞赛或报名字段、碰后台补录，或回答
「谁能报名／截止后还能不能改」时。

---

## 1. 明确不做什么

| 不做 | 落在哪 |
|---|---|
| 联系人／组员身份判定、「谁算管理员」 | `projects.permissions`；本模块只加业务语义名。管理员问 `core.permissions.is_admin` |
| 报名审批 | 有意不做：登记即生效，表上没有状态字段 |
| 竞赛与送审轮次的关联 | 没有这条链路：`ProjectSubmission.review_type` 刻意不与 `Competition` 建外键 |
| 文件上传／取件；概览里的开放竞赛计数 | 本模块没有任何文件字段；计数在 `core.stats.platform_overview`（局部 import `Competition`） |

## 2. 必须成立的断言

- **截止口径只有一处（除了一处重复表达）**：`Competition.is_registration_open` 是唯一口径；
  前台三个入口、前台表单、列表徽章都问它，**后台刻意不问**。但 `core.stats` 的平台概览用
  `is_open=True, deadline__gte=now` 把同一条判定又写了一遍——**改 `is_registration_open` 时要一并核对它**。
- **`save_registration` 自己不看截止**：报名与修改的校验在表单 + 视图各拦一次；放弃只有一个调用方，
  校验写在 `services.withdraw_registration`。**新增前台写入口必须自带这道校验**。
- **同组同赛一条**：`(competition, group)` 唯一约束是本模块唯一由数据库保证的业务规则；
  表单查重只是提示，并发下靠唯一约束兜底（`IntegrityError` → `DuplicateRegistration`），服务层没有行锁。
- **成员归属校验写了两份**：两张表单的 `clean` 各算一次 `group.members` 集合；前台多看一条
  「组长必须在参赛成员内」，后台没有。
- **五个外键一律 `PROTECT`**：删发布人、登记人、组长或已报名的项目组会被数据库挡下。
- **`registered_by` 是首次登记人**，任何修改（含后台）都不改它。
- **名单与操作分开判**：`competition_list` 取全量报名（不再按 `manageable_group_ids`
  过滤），模板逐行拿 `registration.group_id in manageable_group_ids` 决定那一行出不出
  「修改／放弃」。**名单对全体登录成员公开是有意的**，与项目组列表上「评审状态对全体成员可见」
  同一口径（项目组列表本来就列着全部组与成员）；可见范围因此没有另立权限函数，
  真正的写权限边界仍是视图层的 `can_manage_group`。改这一处时别把两者又合成一个查询。
- **项目组详情页上的「竞赛报名」区块归本模块装配**：`panels.group_detail_context`，
  调用方（`projects.views.group_detail`）在函数体内局部 import。区块不判可见性——
  能打开详情页的人就看得到，门槛是 `projects.permissions.can_view_group`。

## 3. 已知限制 / 当前不支持

- **截止时间只约束前台，后台可任意补录**：`CompetitionRegistrationAdminForm` **刻意不看它**，
  `deadline` 在后台也可填任意时间（含已过去）。已截止的竞赛要加项目组，**后台是唯一入口**
  ——这是有意设计；谁在后台表单里补上与前台一致的截止校验，就堵掉了补录这条路。
- **后台不校验「组长是参赛成员之一」**：它只查组长属于项目组，所以后台能造出组长不在参赛成员内的记录。
  这与截止一样，是补录路径的一部分，别顺手「补齐」。
- **人数没有校验**：`team_size` 只是自由文本、只作展示，`members` 的数量不受它约束。
- **无行锁**：两个请求同时报同一组同一赛，一个成功、另一个得到 `DuplicateRegistration`。
- **竞赛页不分页**：所有竞赛与所有报名行在同一页渲染（靠 `select_related` 避免逐行查询）。
  一个社团的规模够用；要按竞赛或按组翻页得另加。
- **删账号或删已报名的项目组会被外键挡下**（`PROTECT`），要删得先处理报名记录。

## 4. 由来

- **为什么外键全是 `PROTECT`**：报名记录是报给主办方的档案，删账号或删已报名的项目组应当被挡下、
  由人先处理。**代码如此，但没有文档说明这是当初的决定还是顺带**——要放宽时先想清档案要不要留。
- **时间端点是闭端**：判定式 `now() <= deadline`——截止那一刻仍可报名。平台上别处还有别的时间端点，
  门槛宽严各不相同；写时间比较前先确认你要的是哪一种，术语表记了这条约定。
