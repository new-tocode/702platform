# 7. 权限设计

> 谁能做什么：角色表、权限矩阵、对象级权限，以及身份的管理方式。

**什么时候看**：加一种身份、改一处判定，或回答「这个功能谁能用」。

---

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
- 「组成员关系」通过 `ProjectGroup.members` 表达；「内部通知的用户组」仍是 Django `auth.Group`（`Notice.visible_groups`），两套"组"语义不同，不可混淆。 反过来，Django `auth.Group` 的成员关系挂在 `User.groups` 上——组页那个穿梭框因此不是模型字段，而是在表单里显式声明、由 `accounts.services.set_group_members` 落库。
- **「谁算管理员」只有一处写法**：`core/permissions.py` 的 `is_admin(user)`（`is_staff` 或 `is_superuser`）。此前 `is_staff` 与 `is_staff or is_superuser` 两种写法并存，同一个问题两个答案；现在各应用一律问它。`projects.permissions.can_decide_group_create_requests` 保留为业务语义名（「谁能审建组申请」），函数体委托 `is_admin`。
- 社团空间的帖子管理沿用 `is_admin()`（staff 或 superuser）；板块管理单独要求 Django `is_superuser`，不能用评审资格代替。空间成员范围是 `is_active=True` 且已完成首次改密的账号。
- **依赖方向**：跨应用引用只经 `permissions`／`services`／`selectors` 的公开函数，且不在模块加载期互相牵连（需要时用函数内局部 import）。`projects` 与 `reviews` 之间原本有一处双向 import，随着 `reviews` 改问 `core.permissions.is_admin` 而消失。

#### 7.1.1 身份的管理：两种作用域，两套办法

平台上的身份按**来源**分成两类，管理方式因此不同。这张表也是后台「身份管理」分组的依据：

| 作用域 | 身份 | 从哪来 | 后台能做什么 |
|---|---|---|---|
| `GLOBAL` | 管理员、评审人、初审人、超级评审 | 管理员**授予**，与任何对象无关 | 用户列表页勾选多人 → 批量授予／撤销（六个动作，写审计）。名册只读 |
| `OBJECT` | 项目组联系人、项目组成员 | 业务动作**产生**：入组申请通过、建组申请通过、联系人转让 | **只能看**——名册不给任何分配入口 |

对象的两种身份为什么不做分配入口：联系人必须依附某个项目组，成员要经入组审批；让管理员随手指定，既绕过了「成员不能被移出」这类业务校验，也让身份与项目组脱节。想改归属，去项目组页（后台的成员穿梭框，或前台的项目组管理页）。

- 身份的**目录**在 `core/roles.py`：登记「有哪些身份、各自叫什么、从哪来」，沿用 `core/registry.py` 的操作入口注册表形状（frozen dataclass + 幂等注册 + `RLock`），各应用在 `AppConfig.ready()` 里登记自己那几种。**判定仍归各应用的 `permissions`**（谁有什么身份），**授予仍归各应用的 `services`**（怎么给出去），目录不重复这两件事。
- 身份的**存储没有变**：全局身份是 `User` 上的布尔字段，对象身份是 `ProjectGroup.leader` 与 `ProjectGroup.members`。后台的六张名册是 `User` 的 proxy model——不建表，也就不存在与布尔字段分叉的第二处真相。统一的是**管理面**，不是存储面。
- 资格的写入只有一处：`accounts.services.set_qualification`（带事务与 `accounts.qualification.grant/revoke` 审计）。可批量改的字段有白名单，**不含 `is_superuser` 与 `is_active`**；也没有「批量授予管理员资格」——把一批人放进后台应当逐个确认。

### 7.2 权限矩阵

| 能力 | 访客 | 无组员 | 组员 | 项目组联系人 | 管理员 |
|---|:---:|:---:|:---:|:---:|:---:|
| 浏览公开通知/展示页 | ✔ | ✔ | ✔ | ✔ | ✔ |
| 登录 / 修改本人资料与密码 | — | ✔ | ✔ | ✔ | ✔ |
| 查看社团空间、成员目录与只读资料 | — | ✔ | ✔ | ✔ | ✔ |
| 发帖、评论、维护自己的帖子 | — | ✔ | ✔ | ✔ | ✔ |
| 删除他人帖子/评论、置顶/取消置顶 | — | — | — | — | ✔ |
| 创建/删除空板块 | — | — | — | — | 仅超级管理员 |
| 浏览内部通知（按 auth 用户组） | — | ✔ | ✔ | ✔ | ✔ |
| 查看"仅联系人可见"通知 | — | — | — | ✔ | ✔ |
| 查看项目组页 | — | ✔（全部，可申请加入） | ✔（仅自己的组） | ✔（全部 + 管理自己的组） | ✔ |
| 申请加入项目组 | — | ✔ | — | — | — |
| 申请创建项目组 | — | ✔ | ✔ | ✔ | ✔ |
| 审核创建项目组申请（同意/拒绝，在「评审」页） | — | — | — | — | ✔ |
| 借用设备 / 查看本人借用记录 | — | — | ✔ | ✔ | ✔ |
| 归还本人已借设备 | — | ✔ | ✔ | ✔ | ✔ |
| 报名竞赛 / 修改 / 放弃报名 | — | — | — | ✔* | ✔ |
| 审核入组申请、移除成员、转让联系人、改组介绍 | — | — | — | ✔* | ✔ |
| 进入 `/admin/` 管理后台 | — | — | — | — | ✔ |
| 发布通知/竞赛、维护设备与账号 | — | — | — | — | ✔ |

\* 项目组联系人仅能管理 `leader == user` 的项目组（对象级权限）；报名/报名修改/放弃同样限自己的组。

**评审人（`User.is_reviewer`）**：额外获得「评审」入口，只能看到分配给自己的送审；可下载项目书、在项目组详情页提交评审意见与决定，并可选附一份批注版项目书；成员中心另有「初审／评审请假」面板，可登记一段不收新任务的时间窗。手上有未完成评审任务时，登录会收到提醒，成员中心顶部也常驻一张待办卡片。项目组详情页对 staff、该组成员、本轮初审人、被分配任务（初审或评审）的账号，以及该组有未结束轮次时的超级评审可见——这几项授权是**并集**，同时具备多种资格的账号不会因为走了某一支而丢掉自己任务带来的可见性（`can_view_group`）。

**管理员（`is_staff`）**：即使一份评审资格都没有也能进入「评审」页（`reviews.permissions.can_open_queue` 在三种资格之外再放行管理员）——项目组创建申请汇总在这里，任一位管理员同意即通过并即刻建组，其他管理员的这条待办随之消失（见 [projects.md](projects.md)）。页面装配在 `reviews.panels.queue_context`：只有管理员拿得到 `create_requests`，评审人拿到的是自己的任务。

**初审人（`User.is_preliminary_reviewer`）**：「评审」入口与队列对**三种资格中的任意一种**开放（`reviews/permissions.py` 的 `has_review_qualification`），但队列里各自只看到自己那一侧：初审人看到「待初审／已完成的初审／已释放的初审」，评审人看到「待评审／已完成的评审／已释放的评审」。

初审人在项目组详情页拿到的是「我的初审」面板（通过 / 需修改 + 意见，没有批注版），可下载项目书；初审**通过**即让该轮进入评审并抽齐评审人，**打回**则本轮直接结束。请假窗口对初审人同样开放（面板与时长口径都叫「初审／评审请假」）。初审人身份对项目组匿名（页面上只写「初审」）。

### 7.3 对象级权限（唯一的复杂度点）

Django 原生支持「组级」权限，**对象级**需自定义；本项目把项目组相关的判定收敛在 `projects/permissions.py`：

- `is_project_contact(user)`：是否是任一项目组的联系人（由 `leader` 计算）。
- `is_project_member(user)`：是否属于任一项目组。
- `can_manage_group(user, group)`：`is_staff` 或 `group.leader_id == user.pk`。
- `can_decide_group_create_requests(user)`：`is_staff` —— 谁能处理创建项目组申请。申请送到管理员的「评审」页，评审侧局部 import 本函数决定给不给看那份待办，视图门槛与页面装配同源。
- `can_use_equipment(user)`：`is_staff` 或 `is_project_member(user)` —— 设备借用门槛。
- `groups_visible_to(user)`：staff/联系人→全部；有组→自己的组；无组→全部（申请模式）。
- `can_view_borrow(borrow, user)`：借用记录本人可见，管理员可见全部。
- **项目组报名权限**：`competitions.permissions.can_register_group` 委托 `can_manage_group`；报名成员与竞赛组长都必须属于所选项目组，且竞赛组长必须是参赛成员之一。
- **通知可见性**：`notices/visibility.py` 的 `member_visible_notices(user)` 单点判定 —— `internal` 走 `visible_groups`，`contacts` 走 `is_project_contact(user)`；列表与详情共用，未命中返回 404。
- **社团空间权限**：`discussion/permissions.py` 集中成员、作者、管理员和超级管理员判定；写操作在服务层再次校验。只有帖子作者可修改自己的帖子，管理员可删任意帖子并置顶；评论的删除口径与帖子对称（作者删自己的、管理员删任意），帖子作者对别人在自己帖子下的评论**没有**删除权。超级管理员才可在前端创建/删除空板块。

建议封装为通用 helper（本项目已用 `projects/permissions.py` + `projects/services.py` 落地；`competitions/permissions.py` 为薄封装）。

---
