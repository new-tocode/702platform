# projects 模块

> 项目组：组本身、联系人（由 `leader` 计算）、指导老师、入组申请、建组申请，以及项目书的校验、上传与取件。
> 不做评审本身（轮次、任务、结论、批注版归档都在 `reviews`），不存任何联系人／成员身份；
> `reviews`、`competitions`、`equipment`、`notices`、`accounts` 都来问它的 `permissions`／`selectors` 取口径。

**什么时候看**：改项目组成员关系、指导老师槽位、入组／建组申请流程，或回答「谁能看、谁能管这个项目组」时。

---

## 1. 明确不做什么

| 不做 | 落在哪 |
|---|---|
| 评审本身：送审轮次、初审／评审任务、结论、批注版、归档 | `reviews`。本模块只在 `group_submit_review` 里转交 `reviews.services.submit_for_review`，详情页的评审区块由 `reviews.panels.group_detail_context` 装配 |
| 评审资格判定，以及「凭评审身份能不能看这个组」 | `reviews.permissions`（`has_review_claim`）。`can_view_group` 只委托这一次，不在本模块重写 |
| 教师账号、把指导老师关联成用户 | 不做：指导老师是纯文本姓名，没有可指向的账号 |
| 存联系人／成员身份（auth 用户组、独立 membership 表） | 不做：身份由 `ProjectGroup.leader` / `.members` 计算；后台只给只读名册，不给分配入口 |
| 「谁算管理员」 | `core.permissions.is_admin`。`can_decide_group_create_requests` 只是业务语义名，函数体委托过去 |
| 受保护件的 HTTP 响应 | `core.downloads.serve_file`。本模块判权限后调用，并把 `group.sha256` 附上响应头 |
| 消息的呈现与去向 | `notices`。本模块只在服务里调 `notices.services` 写事件消息 |

## 2. 必须成立的断言

- **联系人恒为成员**——唯一一条靠代码而不是数据库约束保证的不变量：
  - `ProjectGroup.save()` 每次保存都 `members.add(leader_id)`，且**只增不减**。
  - 后台的 `filter_horizontal` 在 `save()` **之后**整份覆盖 `members`，所以 `ProjectGroupAdmin.save_related`
    末尾再调一次 `services.sync_group_membership()` 补回来。**任何新的「整份覆盖 members」的写入路径
    都必须保留这一步**。
  - 后果：`is_project_member` 认的联系人一定在同一张成员名单里，`selectors.groups_of_member`
    与后台名册的口径因此一致。
- **联系人只有一个写入来源**：`ProjectGroup.leader`。没有用户组、没有 membership 表；
  `contact_group_ids`／`member_group_ids`／`manageable_group_ids`／`groups_visible_to`
  与后台两个名册都从它派生。换归属只有两条业务路径：建组申请通过、组内转让。
- **同一申请人同时只有一条待审申请**：两类申请各靠一条部分唯一约束兜底（只限 `pending`），
  被拒后可重新申请；并发下服务层把 `IntegrityError` 翻成领域异常。
- **指导老师上限 3 位、只写一处**：`MAX_ADVISORS_PER_GROUP` 是唯一写法，模型两条约束、
  `ADVISOR_SLOT_CHOICES`、`_advisor_slots()`、`_advisor_names_or_raise()`、`ProjectAdvisorInline.max_num`
  都从它导出。但 `GroupCreateRequest.advisor_1..3` 是三个写死的列、两张表单也各自显式声明三个字段
  ——**把上限提到 3 以上要动迁移，不只是改常量**。
- **槽位无空洞**：`update_group_info` 按槽位升序处理——空槽位删行，其余名字向前收拢到 0..n-1。
  这是 `(group, sort_order)` 唯一约束在编辑时始终可满足的原因；保留空洞或乱序写入会撞约束。
- **申请状态只有一个写入点**：`services` 里那四个 `approve_*/reject_*` 函数，全部在事务内先
  `select_for_update()` 再复查 `pending`。后台对两张申请表是 `ReadOnlyAdminMixin`，只能看。
- **唯一真相源清单**：联系人身份 → `ProjectGroup.leader`；指导老师上限 → `MAX_ADVISORS_PER_GROUP`；
  轮次与任务状态 → `reviews.lifecycle.transition()`（不属于本模块）。
- **锁的是申请行，不是组行**：两个人同时点通过，第二个在锁后复查到状态已变，得到「该申请已被处理」。
  入组与建组两条路都是这个形状（**真并发没有用例**，见下）。

## 3. 已知限制 / 当前不支持

- **可以同时向多个组各留一条待审申请**：唯一约束只按 `(组, 人)`，一个人手里同时压着三份
  「申请审核中」是允许的（页面在卡片上标状态，联系人也各自只看自己的组）。
- **`group_apply` 不判可见范围，是有意的**：列表已经列全部组，直接访问 `/member/projects/<id>/apply/`
  与从列表点进来是同一件事；那里唯一的门槛是「还不是该组的成员」。
- **卡片上的评审状态是「最近一轮」的**：`status_label` / `status_tone` 取该组最新一轮的状态
  （没有轮次就不出 chip）。**这是有意给全体成员看的**——列表本来就列着每个组的简介、成员名单与
  指导老师，评审进度不再算额外暴露；详情页那份完整历史仍按 `can_view_group` 收着。
- **列表卡片的详情链接与详情页门槛不是同一个函数**：`group_list` 里的 `can_view` 判的是
  「管理员或本组成员」，不是 `can_view_group`；评审人凭任务能打开详情页，但列表不会因此多出链接。
- **「联系人恒为成员」没有数据库约束**：只靠 `ProjectGroup.save()` 与后台 `sync_group_membership()`
  两处补偿。`QuerySet.update()`、直接 `members.remove(leader)`、或任何跳过 `save()` 的写入都会破坏它。
- **提高指导老师上限要动迁移**：`GroupCreateRequest.advisor_1..3` 是三个固定列，
  `GroupCreateRequestForm` / `GroupInfoForm` 也各自显式声明三个字段；常量之外这些地方都要跟着改。
- **项目书原文件名不留存**：落盘名是 uuid + 扩展名，页面展示与下载头里都是它——上传时的文件名
  （常带组名、人名）平台根本不保存。
- **建组申请发给全体管理员的那批消息不会被撤回**：任一管理员处理后，其余人的队列里那条申请消失了，
  消息却还在（点进去看不到东西）。这是现状，不是漏写；要改成撤回得在 `notices` 加一条清理路径。
- **并发只覆盖顺序的第二次提交**：建组申请的「两个管理员同时同意」靠服务层的行锁 + 复查挡住，
  **没有测试钉住真并发**。

## 4. 由来

- **为什么建组申请用三个固定列**（`advisor_1..3`）而不是子表：申请不是项目组，不为临时草稿建子表；
  代价是把上限提到 3 以上要动迁移。
