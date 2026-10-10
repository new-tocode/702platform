# projects 模块

> 项目组：组本身、联系人（由 `leader` 计算）、指导老师、入组申请、建组申请，以及项目书的校验、上传与取件。不做评审本身（轮次、任务、结论、批注版归档都在 `reviews`），不存任何联系人/成员身份；`reviews`、`competitions`、`equipment`、`notices`、`accounts` 都来问它的 `permissions`／`selectors` 取口径。

**什么时候看**：改项目组成员关系、指导老师槽位、入组／建组申请流程，或回答「谁能看、谁能管这个项目组」时。

---

## 1. 职责与边界

**负责什么**

| 面 | 落点 |
|---|---|
| 表与不变量 | `models.py`：`ProjectGroup`、`ProjectAdvisor`、`GroupJoinRequest`、`GroupCreateRequest`，外加两个只读名册代理 `ProjectContact` / `ProjectMember` |
| 判定 | `permissions.py`：联系人／成员身份、对象级管理权、列表可见范围 |
| 写操作 | `services.py`：两类申请的提交与处理、成员移除、联系人转让、组信息维护 |
| 只读查询 | `selectors.py`：按人取组（`groups_led_by` / `groups_of_member`）、按关键字搜组（`search_groups`） |
| 项目书 | `validators.py` 校验；上传在 `group_proposal_update`；取件口 `group_proposal_download`（受保护件） |
| 页面 | `group_list` / `group_detail` / `group_apply` / `group_create_request` / `group_manage` 与五个 POST 动作视图；路由在 `urls.py`，挂载于 `config/urls.py` 的 `member/projects/` |
| 登记 | `apps.py` 向 `core.registry` 注册入口 `projects.groups`，向 `core.roles` 注册对象身份 `project_contact`、`project_member`（`Scope.OBJECT`，只给名册） |

**明确不做什么**

| 不做 | 落在哪 |
|---|---|
| 评审本身：送审轮次、初审／评审任务、结论、批注版、归档 | `reviews`。本模块只在 `group_submit_review` 里转交 `reviews.services.submit_for_review`，详情页的评审区块由 `reviews.panels.group_detail_context` 装配 |
| 评审资格判定，以及「凭评审身份能不能看这个组」 | `reviews.permissions`（`has_review_claim`）。`can_view_group` 只委托这一次，不在本模块重写 |
| 教师账号、把指导老师关联成用户 | 不做：指导老师是纯文本姓名，没有可指向的账号（`docs/architecture/overview.md` §1.1） |
| 存联系人／成员身份（auth 用户组、独立 membership 表） | 不做：身份由 `ProjectGroup.leader` / `.members` 计算；后台只给只读名册，不给分配入口（`docs/architecture/permissions.md` §7.1.1） |
| 「谁算管理员」 | `core.permissions.is_admin`。`can_decide_group_create_requests` 只是业务语义名，函数体委托过去 |
| 受保护件的 HTTP 响应 | `core.downloads.serve_file`。本模块判权限后调用，并把 `group.sha256` 附上响应头 |
| 消息的呈现与去向 | `notices`（`notices.selectors`）。本模块只在服务里调 `notices.services` 写事件消息。**细节**：建组申请发给全体管理员的那批消息**不会被撤回**——任一管理员处理后，其余人的队列里那条申请消失了，消息却还在（点进去看不到东西）。这是现状，不是漏写；要改成撤回得在 `notices` 加一条清理路径 |

**所属层与依赖方向**

- 成员前台 + Django Admin；服务端渲染，没有 API 层。
- 上游：`core`（`permissions`／`audit`／`storage`／`hashing`／`downloads`／`registry`／`roles`）、`notices.services`。
- 下游：`reviews`（`ProjectGroup` 外键、`can_view_group` 作评审页门槛、`GroupCreateRequest` 作管理员待办、`validate_proposal_file` 复用到批注版）、`competitions`（`can_manage_group`、`is_project_contact`）、`equipment`（`can_use_equipment`）、`notices`（`is_project_contact` 广播、消息表两个外键）、`accounts`（`contact_group_ids`／`member_group_ids`、`groups_led_by`／`groups_of_member`）、`core.stats`（`is_project_contact`、组数）。
- **projects 不在加载期依赖 reviews**：所有指向 reviews 的 import 都在函数体内（`can_view_group` 的 `has_review_claim`、`group_list` 的 `ProjectSubmission`、`group_detail` 的 `panels`、`group_submit_review` 的 `forms`／`services`）。别把它们挪到模块顶部。

## 2. 关键接口与失败模式

权限函数只返回布尔或查询集，**从不抛异常**；403 全部产生在视图层。

| 入口 | 语义 | 前置条件 | 失败模式 |
|---|---|---|---|
| `permissions.can_manage_group(user, group)` | 管理员或该组联系人（`group.leader_id == user.pk`） | 视图已取到组对象 | 假 → `_require_group_manager` 走 `core.permissions.require`，记 `project_group.permission.denied` 警告并抛 `PermissionDenied`（**403**）。管理页与其全部写动作、上传项目书、送审共用这一个门槛 |
| `permissions.can_view_group(user, group)` | 管理员／该组成员／评审主张（委托 `has_review_claim`），几项**取并集** | — | 假 → **403**（`group_detail`、`group_proposal_download`）；组不存在则先 404 |
| `permissions.can_decide_group_create_requests(user)` | 全体管理员（委托 `core.permissions.is_admin`） | — | 假 → `group_create_decide` 记 `project_group.create.decide.denied` 警告后 **403**；`action` 不是 `approve`/`reject` → 404 |
| `permissions.groups_visible_to(user)` | 列表与「我的项目组」的范围：staff／联系人→全部，有组→自己的组，无组→全部（申请模式），未登录→空 | — | 不抛异常。这里判错只影响列表多／少行，不构成越权——详情与取件另有 `can_view_group` |
| `services.apply_to_group(group, applicant, message)` | 新建或刷新一条待审入组申请 | 已登录、尚不是该组成员 | 未登录／已是成员／并发撞部分唯一约束 → `JoinRequestError`，视图 `messages.error` + 302 回列表（不是 4xx） |
| `services.approve_join_request` / `reject_join_request` | 落定一条待审申请；通过时把申请人写进 `members` | 调用方已过 `can_manage_group`；申请仍为 `pending` | 已处理 → `JoinRequestError("该申请已被处理。")` → 302 回管理页 |
| `services.apply_to_create_group(applicant, name, description, college, advisor_names)` | 新建或整份刷新一条待审建组申请 | 已登录；指导老师 ≤ `MAX_ADVISORS_PER_GROUP` | 超限／并发撞部分唯一约束 → `GroupCreateRequestError` → 302 回列表 |
| `services.approve_create_request` / `reject_create_request` | 建组（申请人即联系人，指导老师按槽位落行）或驳回 | 调用方为管理员；申请仍为 `pending` | 已处理 → `GroupCreateRequestError("该申请已被处理。")`；处理完统一 302 回 `reviews:queue` |
| `services.remove_group_member` / `transfer_contact` / `update_group_info` | 成员移除、联系人转让、学院与指导老师维护 | 调用方已过 `can_manage_group` | `GroupManagementError`：联系人不可移除／新联系人必须是组员／指导老师超限 → `messages.error` + 302 |
| `views.group_proposal_download` | 项目书取件口（受保护件） | `can_view_group` 为真；组有项目书 | 无权限 → **403**；没有项目书 → `Http404`（**404**）；组不存在 → 404 |

- `selectors.search_groups(groups, query)` 不判权限，可见范围由调用方先用 `groups_visible_to` 收窄；跨 `members`／`advisors` 过滤会 JOIN 出多行，结尾用 `distinct` 收回。**注意它与 `member_count` 的关系**：两者落在同一条 member join 上，所以按成员姓名搜索时，卡片上的人数会跟着过滤变小（`distinct=True` 挡不住这个）——详见 §6 的已知限制。

## 3. 状态与不变量

**表与决定行为的字段**

| `ProjectGroup` 字段 | 决定什么 |
|---|---|
| `leader` | 联系人身份的**唯一真相源**；`on_delete=PROTECT`，`related_name="led_project_groups"` |
| `members` | 成员关系；`save()` 保证联系人也在名单里（见下） |
| `proposal` | 受保护件：`private_storage` + `neutral_upload_to("project_proposals")`，落盘名是 uuid + 原扩展名；校验走 `validate_proposal_file` |
| `sha256` | `FileDigestMixin`（`digest_field="proposal"`）在保存时自动维护，`editable=False` 不进表单；取件时经 `serve_file(sha256=...)` 随响应头送出 |
| `description` / `college` | 组信息里的自由文本，由联系人在管理页维护（上限 2000 / 128） |

| `ProjectAdvisor` | 决定什么 |
|---|---|
| `sort_order` | 槽位 0/1/2（`ADVISOR_SLOT_CHOICES`），后台选单据此生成；真正的「至多 3 位」靠下面两条约束 |
| 约束 | `UniqueConstraint(group, sort_order)` + `CheckConstraint(sort_order < MAX_ADVISORS_PER_GROUP)`，两条合起来就是「每组至多 3 位」 |

| 申请表 | 约束与要点 |
|---|---|
| `GroupJoinRequest` | `(group, applicant) WHERE status='pending'` 部分唯一；`group`／`applicant` 都是 PROTECT（有申请历史就删不掉组或账号）；索引 `(group, status)`、`(applicant, status)` |
| `GroupCreateRequest` | `(applicant) WHERE status='pending'` 部分唯一；`description` 必填；指导老师是 `advisor_1..3` 三个固定列（申请不是项目组，不为它建子表），通过时按 `filled_advisor_names` 的顺序转成槽位 0..n-1 的 `ProjectAdvisor` 行；`created_group` 是 OneToOne(PROTECT)，建组后回填 |
| 两个代理 | `ProjectContact` / `ProjectMember` 是 `User` 的 proxy，不建表，只给后台名册看 |

**不变量**

- **联系人恒为成员**——唯一一条靠代码而不是数据库约束保证的不变量：
  - `ProjectGroup.save()` 每次保存都 `members.add(leader_id)`，且**只增不减**。
  - 后台的 `filter_horizontal` 在 `save()` **之后**整份覆盖 `members`，所以 `ProjectGroupAdmin.save_related` 末尾再调一次 `services.sync_group_membership()` 补回来。任何新的「整份覆盖 members」的写入路径都必须保留这一步。
  - 后果：`is_project_member` 认的联系人一定在同一张成员名单里，`selectors.groups_of_member` 与后台名册的口径因此一致。
- **联系人只有一个写入来源**：`ProjectGroup.leader`。没有用户组、没有 membership 表；`contact_group_ids`／`member_group_ids`／`manageable_group_ids`／`groups_visible_to` 与后台两个名册都从它派生。换归属只有两条业务路径：建组申请通过、组内转让。
- **同一申请人同时只有一条待审申请**：两类申请各靠一条部分唯一约束兜底（只限 `pending`），被拒后可重新申请；并发下服务层把 `IntegrityError` 翻成领域异常。
- **指导老师上限 3 位、只写一处**：`MAX_ADVISORS_PER_GROUP` 是唯一写法，模型两条约束、`ADVISOR_SLOT_CHOICES`、`_advisor_slots()`、`_advisor_names_or_raise()`、`ProjectAdvisorInline.max_num` 都从它导出。但 `GroupCreateRequest.advisor_1..3` 是三个写死的列、两张表单也各自显式声明三个字段——把上限提到 3 以上要动迁移，不只是改常量。
- **槽位无空洞**：`update_group_info` 按槽位升序处理——空槽位删行，其余名字向前收拢到 0..n-1。这是 `(group, sort_order)` 唯一约束在编辑时始终可满足的原因；保留空洞或乱序写入会撞约束。
- **申请状态只有一个写入点**：`services` 里那四个 `approve_*/reject_*` 函数，全部在事务内先 `select_for_update()` 再复查 `pending`。后台对两张申请表是 `ReadOnlyAdminMixin`，只能看。
- **唯一真相源清单**：联系人身份 → `ProjectGroup.leader`；指导老师上限 → `MAX_ADVISORS_PER_GROUP`；轮次与任务状态 → `reviews.lifecycle.transition()`（不属于本模块）。

## 4. 数据流与时序

### 入组申请（申请 → 联系人审批）

1. `group_apply` GET 渲染 `GroupJoinRequestForm`；POST 前先查 `group.members.filter(pk=request.user.pk)`——已是成员 → `messages.info` + 302 回列表，不建申请也不是错误。
2. 表单有效 → `services.apply_to_group(group, applicant, message, request)`。
3. 服务里登录与成员身份各复查一次（防绕过视图）→ `transaction.atomic()` 内 `get_or_create(group, applicant, status=pending)`；命中已有待审申请时**只在本次填了理由时**覆盖 `message`；同事务内 `notices_services.notify_join_request`——收件人是这一刻的 `group.leader`，`get_or_create` 幂等，重复申请不堆消息。
4. 事务外 `record_audit("projects.join.apply")` + `logger.info`。撞上部分唯一约束 → `JoinRequestError`。
5. 审批：`group_request_decide`（POST）→ `_require_group_manager`（403）→ `get_object_or_404(GroupJoinRequest, pk=req_pk, group=group)`，申请不属于这个组 → 404。
6. `approve_join_request`：锁申请行 → 复查 `pending` → 写状态／处理人／处理时间 → `members.add(applicant)` → 同事务 `notify_join_result`；`reject_join_request` 只写状态与通知。两者都在事务外审计 `projects.join.approve`／`reject`。
7. **锁的是申请行，不是组行**：两个人同时点通过，第二个在锁后复查到状态已变，得到「该申请已被处理」。

### 建组申请（申请 → 任一管理员同意）

1. `group_create_request` 任何登录成员可进；先取自己的待审申请，用它作表单 `instance`——再进来是改，不是从头填。
2. `apply_to_create_group`：`_advisor_names_or_raise` 归一化（去空白、卡上限）→ `transaction.atomic()` 内 `get_or_create(applicant, status=pending)`；已有待审就整份覆写 `name`/`description`/`college`/`advisor_1..3`；同事务 `notify_create_request`——给**申请这一刻**在册的全体管理员各写一条；并发撞唯一约束 → `GroupCreateRequestError`。
3. 事务外审计 `projects.group.create.apply` + `logger.info`。
4. 处理：`group_create_decide`（POST，管理员，403 见 §2）→ `approve_create_request`：锁申请行 → 复查 `pending` → 同一事务里建 `ProjectGroup`（`leader=locked.applicant`，`save()` 顺手把申请人加进成员）→ 按 `filled_advisor_names` 落成 `ProjectAdvisor` 行（槽位 0..n-1）→ 回填申请的 `status`/`decided_by`/`decided_at`/`created_group` → `notify_create_result`。
5. `reject_create_request` 同理，只写状态与通知。
6. 建组、指导老师、申请状态、结果消息**全在一个事务里**；审计在事务外。视图无论成败都 `redirect("reviews:queue")`——入口与出口都在管理员的「评审」页。

### 联系人转让

1. `group_manage` POST `action=transfer` → `ContactTransferForm(group, request.POST)`；下拉范围是 `group.members.exclude(pk=group.leader_id)`，`clean_new_contact` 再查一次成员身份。
2. `services.transfer_contact`：成员校验失败 → `GroupManagementError`；`transaction.atomic()` 内改 `leader` 并 `save(update_fields=["leader", "updated_at"])`。
3. `ProjectGroup.save()` 只 `add` 当前联系人、从不移除，所以原联系人留在成员名单里（转让后就是普通成员）；新联系人本就是成员，这一步是空操作。
4. 事务外审计 `projects.contact.transfer`，记 `previous_contact_id` 与 `new_contact_id`。

### 上传项目书（`group_proposal_update`）

1. `_require_group_manager`（403）→ `GroupProposalForm`；受保护件必须用 `ProtectedClearableFileInput`，否则「当前文件／清除」整块不渲染。
2. 校验全在 `validators.validate_proposal_file`：扩展名 ∈ {pdf, doc, docx}、≤ 20 MB、文件头签名；不合格逐条 `messages.error`，不写库。
3. 这是本模块**唯一**直接 `form.save()` 的写操作（不进 services）；`FileDigestMixin` 在保存时算 `sha256`，视图随后 `record_audit("projects.group.proposal.update")`。
4. 下载：`group_proposal_download` 判 `can_view_group`（403）→ 没有项目书 404 → `serve_file(..., as_attachment=True, sha256=group.sha256)`；下载名是落盘名（uuid + 后缀），不是上传时的原名。

## 5. 错误处理与诊断

**领域异常 → 页面提示**

| 异常 | 谁抛 | 视图怎么翻 |
|---|---|---|
| `JoinRequestError` | `apply_to_group`、`approve/reject_join_request` | `group_apply` / `group_request_decide`：`messages.error(str(exc))` + 302（异常消息本身就是用户可见文案，用 `gettext_lazy`） |
| `GroupCreateRequestError` | `apply_to_create_group`、`approve/reject_create_request` | `group_create_request` / `group_create_decide`：同上 |
| `GroupManagementError` | `remove_group_member`、`transfer_contact`、`update_group_info` | `group_manage` / `group_member_remove`：同上 |

- 门槛拒绝一律 **403**，样板收在 `core.permissions.require(request, predicate, event, **fields)`：`_require_group_manager` 的 `event="project_group.permission.denied"`（附 `group_id`）；`group_detail` 与 `group_create_decide` 自己 `raise PermissionDenied`，但都先记一条 warning（`project_group.detail.denied` / `project_group.create.decide.denied`）。**一处例外**：`group_proposal_download` 的越权是**裸抛、不留日志**——排查「谁在试取项目书」时这一支是静默的。
- **404 用于「对象不存在／不属于当前上下文」**：组不存在、入组申请不属于该组、`action` 不是 `approve`/`reject`、组没有项目书。
- 审计 action（一旦发布不再改，见 `docs/glossary.md` 的「审计 action」）：
  - 申请：`projects.join.apply` / `projects.join.approve` / `projects.join.reject`、`projects.group.create.apply` / `projects.group.create.approve` / `projects.group.create.reject`。
  - 组：`projects.group.proposal.update`（视图）、`projects.group.description.update`、`projects.group.info.update`、`projects.contact.transfer`、`projects.member.remove`。
  - 后台：`projects.group.create` / `projects.group.update`（`save_model`）、`projects.group.membership.create` / `projects.group.membership.update`（`sync_group_membership`）。
- 日志：logger 名就是模块路径（`projects.views` / `projects.services` / `projects.admin`），一律带 `extra={"request_id": ...}`。常用锚点：`project_group.list.view`、`project_group.detail.denied`、`project_group.create.decide.denied`、`project_group.join.apply`、`project_group.create.apply`、`project_group.create.approve`、`admin.project_group.save`。审计写入本身另记一条 `audit.record`。
- **刻意不报错**：
  - 已是成员再点申请 → `messages.info` + 跳列表，不建申请、不抛异常。
  - 重复提交待审申请 → 刷新同一条记录（入组申请只在填了理由时刷），消息靠 `get_or_create` 幂等。
  - 同一份建组申请被第二位管理员处理 → 正常得到「该申请已被处理」，不是故障。
  - 搜索关键字为空 → 原样返回查询集，不算错误。
  - 落盘文件缺失时 `FileDigestMixin` 只记 `file_digest.missing` 警告，不打断保存（指纹会变空，是运维要看的信号）。

## 6. 测试要点与已知限制

**测试文件各钉住什么**

| 文件 | 钉住 |
|---|---|
| `tests/base.py` | 共享夹具 `ProjectViewTestCase`：管理员／联系人／组员／无组者／另一个联系人 + 两个组；把 `PRIVATE_MEDIA_ROOT` 指到临时目录，真上传的用例不再往仓库的 `protected_media/` 里留孤儿文件 |
| `tests/test_browsing.py` | `GroupBrowsingViewTests`（联系人自动入组；组员只看自己的组；无组者看全部可申请；联系人看到管理链接；匿名跳登录；详情从项目书文件名取扩展名；学院与指导老师两页都显示；没指导老师时用占位符）、`GroupListSearchTests`（关键字扫组名与联系人／成员／指导老师姓名、`username` 兜底、`distinct` 不重复出组、不越可见范围、空关键字、无命中空态）、`GroupListMineFilterTests`（`?mine=1` 三种身份的结果，与关键字及链接参数共存） |
| `tests/test_membership.py` | 申请→通过写进 `members`；重复待审申请只留一条；被拒后可重申；联系人可移除成员；**联系人不可被移除** |
| `tests/test_contact_transfer.py` | 转让后原联系人仍是普通成员 |
| `tests/test_group_management.py` | 管理页只对联系人／管理员开（其他人 403）；后台建组时联系人留在成员里；管理页各区块渲染得出来；上传项目书落 `sha256` 且完整渲染；**清空槽位后名字收拢、不留空洞**；上限从服务层也无法突破 |
| `tests/test_group_create_requests.py` | 任何登录成员可申请；只要名称 + 描述；重复申请刷新同一条；申请人看到「审核中」而不是按钮；审核入口不在本页；任一管理员同意即建组（联系人、指导老师槽位、学院照搬）；第二位管理员得到「该申请已被处理」且不建第二个组；被拒可重申；**非管理员 403** |
| `tests/test_member_roster.py` | 名册一行一个组并标出组内身份；没组的人不上名册；名册没有新增入口（403） |
| `tests/test_request_messages.py` | 消息的收件人与幂等（申请给联系人／全体管理员，结果给申请人）；消息行的说明现取、链接指向能办事的页面（组详情／评审页／新建的组） |

**已知限制 / 当前不支持**

- **搜索与成员数共用一条 join（未修）**：`search_groups` 过滤与 `Count("members")` 聚合落在同一个 member join 上，按成员姓名搜索只命中一人时，卡片的人数会跟着变小；`distinct=True` 只挡 `advisors` 那处 join 的重复行。要修得让聚合不受过滤影响（子查询，或 `annotate` 早于过滤），动前先想清卡片数字**应该**是哪一个。
- **`group_apply` 不判可见范围**：它只查「是否已是本组成员」，不调 `can_view_group`。列表页对已有组的人只列自己的组，但直接访问 `/member/projects/<id>/apply/` 可以向任意组提交申请，且可以同时向多个组各留一条待审（唯一约束只按 `(组, 人)`）。这是有意还是漏判，代码与文档都没有说明。
- **列表卡片的详情链接与详情页门槛不是同一个函数**：`group_list` 里的 `can_view` 判的是「管理员或本组成员」，不是 `can_view_group`；评审人凭任务能打开详情页，但列表不会因此多出链接。
- **「联系人恒为成员」没有数据库约束**：只靠 `ProjectGroup.save()` 与后台 `sync_group_membership()` 两处补偿。`QuerySet.update()`、直接 `members.remove(leader)`、或任何跳过 `save()` 的写入都会破坏它。
- **提高指导老师上限要动迁移**：`GroupCreateRequest.advisor_1..3` 是三个固定列，`GroupCreateRequestForm` / `GroupInfoForm` 也各自显式声明三个字段；常量之外这些地方都要跟着改。
- **项目书原文件名不留存**：落盘名是 uuid + 扩展名，页面展示与下载头里都是它（术语表的「落盘名」）——上传时的文件名（常带组名、人名）平台根本不保存。
