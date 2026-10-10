# projects

> 项目组、联系人、指导老师与两类申请。**模块说明（职责、接口、不变量、失败模式、测试与限制）在
> [`projects/README.md`](../../projects/README.md)**——表结构、规则与坑都搬去了那里。
>
> 这一篇只留**跨模块口径与由来**。

**什么时候看**：改一处判定却不确定该问谁、想知道建组流程为什么长这样，或要碰「谁能看这个项目组」。

---

## 跨模块口径

- **联系人身份是对象级的、算出来的**（`ProjectGroup.leader`，不建用户组）：`reviews`、`competitions`、`equipment`、`notices`、`core.stats` 都来问 `projects.permissions` 的判定函数（`is_project_contact` / `is_project_member` / `can_manage_group` / `can_use_equipment` / `groups_visible_to`），别各自算一遍。
- **`can_view_group` 是跨 app 的门槛**：它把项目组侧（staff／该组成员）与评审侧（`reviews.permissions.has_review_claim`）**取并集**，评审队列页与三处受保护件取件都拿它当门槛。改动它会影响评审侧的准入——并集意味着不许提前 `return`，否则同时具备多种资格的账号会丢掉任务带来的可见性。
- **建组申请的处理入口在评审页**（`reviews:queue`），不在项目组页：管理员不需要评审资格，`reviews.permissions.can_open_queue` 为此对 `is_staff` 单独放行；「谁算管理员」的口径仍取自 `can_decide_group_create_requests` 一处。

## 由来

- **为什么联系人存 `leader` 而不是用户组**：存两份必然分叉。判定收敛在一处，其他模块复用。
- **为什么指导老师是纯文本**：平台没有教师账号体系；做成外键就要先有那套体系。每组至多 3 位，上限只有 `MAX_ADVISORS_PER_GROUP` 一处写法。
- **为什么建组申请用三个固定列**（`advisor_1..3`）而不是子表：申请不是项目组，不为临时草稿建子表；代价是把上限提到 3 以上要动迁移。
- **为什么卡片上的成员数走子查询**（`selectors.annotate_member_count`）：按姓名搜索时 `search_groups` 已经 JOIN 了 `members`，`Count("members")` 落在那条**被过滤过的** join 上，数出来的是「命中的那几个人」——搜一名成员、卡片写「成员 1 人」，同屏名单却列着 5 个。子查询让计数与过滤各走一条 join，数字恒等于名单长度。「聚合早于过滤」也能得到同样的结果，但那依赖 ORM 何时复用 join，读代码看不出来；子查询把意图写在明面上。
- **依赖方向**：`reviews` 在加载期依赖 `projects`（`ProjectGroup` 外键、`can_view_group`），反向只在函数体内局部 import。历史上这里曾有一处双向 import，随着 `reviews` 改问 `core.permissions.is_admin` 而消失——别把它加回来。
