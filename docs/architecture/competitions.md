# competitions

> 竞赛与报名。**模块说明（职责、接口、不变量、失败模式、测试与限制）在
> [`competitions/README.md`](../../competitions/README.md)**——表结构、规则与坑都搬去了那里。
>
> 这一篇只留**跨模块口径与由来**。

**什么时候看**：改报名规则、动后台补录这条路，或弄清「送审类型」与本模块为什么没有关系。

---

## 跨模块口径

- **截止时间只约束前台**：`Competition.is_registration_open` 是唯一口径；**后台不受它限制**——`deadline` 可填已过去的时间，报名可在任何时候补录、修改、删除，把项目组加进已截止的竞赛**只有后台这一条路**。`AdminDeadlineOverrideAcceptanceTests` 是这条设计的护栏；谁若在 admin 表单里补上与前台一致的截止校验，就堵掉了补录。
- **前台三件事共用同一个判定**：报名、修改、放弃同受 `is_registration_open` 约束。`services.save_registration` **自己不查截止**（查询单在表单与视图那一侧）；新增前台写入口必须自带这道校验，否则口径会分叉。
- **报名权限委托项目组侧**：`competitions.permissions.can_register_group` 是 `projects.permissions.can_manage_group` 的薄封装（对象级：联系人只管自己的组）；`context_processors` 决定报名入口显不显示——与视图门槛同源。
- **送审类型与竞赛没有外键**：评审的 `review_type`（竞赛立项／省赛／国赛……）是平台内标签，刻意不与 `Competition` 关联，两边各管各的。
- **跨模块标识符**：唯一约束名 `unique_competition_group_registration`、操作入口注册表 key `competitions.registration`（被 `core/tests/test_registry_and_audit.py` 钉住）、七个审计 action 字符串（`competitions.create`／`.update` 与报名相关的五个）——都是对外承诺，改之前先搜引用。**截止判定还有一处重复表达**：`core.stats` 的平台概览另写了同一条查询条件。

## 由来

- **为什么没有审批流**：登记即生效。加审批要引入状态机与待办，而这件事没有争议性（见 [overview.md](overview.md) §1.1）。
- **为什么外键全是 `PROTECT`**：报名记录是报给主办方的档案，删账号或删已报名的项目组应当被挡下、由人先处理。**代码如此，但没有文档说明这是当初的决定还是顺带**——要放宽时先想清档案要不要留。
- **时间端点是闭端**：判定式 `now() <= deadline`——截止那一刻仍可报名。平台上别处还有别的时间端点（如通知的发布时间），门槛宽严各不相同；写时间比较前先确认你要的是哪一种，术语表记了这条约定。
- **后台表单不校验「竞赛组长在参赛成员内」**：那条校验只在前台表单里，后台刻意留宽（与截止一样，是补录路径的一部分）。别顺手「补齐」，先想清是否故意。
