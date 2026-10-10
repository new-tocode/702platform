# reviews 模块

> 项目书同行评审：一轮送审先过**初审关卡**，通过后按送审类型随机抽齐评审人，全员通过才算通过，通过轮的批注版项目书归档；另有请假、改派与超级评审一票敲定。它不做身份授予（归 `accounts`）、不存项目书本体（在 `ProjectGroup.proposal`，归 `projects`）、不写用户可见通知（归 `notices`）、不判项目组可见性的项目组侧（归 `projects.permissions`）。`projects`、`accounts`、`notices` 与操作入口注册表都在用它。

**什么时候看**：改送审与轮次状态、初审关卡、抽签与配额、结论汇总与归档、请假、改派、超级评审，或动评审队列页、项目组详情页的评审区块、`ProjectSubmission`／`ReviewTask`／`ArchivedProposal`／`ReviewerLeave` 的时候。术语口径以 [../docs/glossary.md](../docs/glossary.md) 为准。

---

## 1. 职责与边界

**负责**

- 一轮送审的生命周期：状态机、单轮次约束、轮次号（`ProjectSubmission`）。
- 两道关的任务：每轮 1 条初审 + 按配额 N 条评审，抽签、改派、超级评审释放（`ReviewTask`）。
- 结论：两道关共用 `approve`／`revise`；初审通过才抽评审人，评审**全员通过**才通过，任一「需修改」即打回。
- 归档：通过轮次上「已完成且通过」的批注版复制为 `ArchivedProposal`。
- 请假：`ReviewerLeave` 窗口，以及它在抽签与改派候选中的排除。
- 超级评审一票敲定（含初审中的轮次）。
- 页面：评审队列 `reviews:queue`（管理员处理建组申请的待办也在此）、项目组详情页的评审区块、成员中心的请假面板、批注版与归档件的取件。
- 资格判定：`is_reviewer`／`is_preliminary_reviewer`／`is_super_reviewer`／`qualifies_for_stage`。

**明确不做**

| 不做什么 | 落在哪 |
|---|---|
| 项目书本体的保存与上传校验 | `ProjectGroup.proposal`（`projects`），格式/大小由 `projects.validators.validate_proposal_file` 管；**评审只读它、从不复制**，各轮次共用同一份 |
| 项目组、联系人、成员、指导老师 | `projects` |
| 建组申请的模型与处理 | `projects`（`GroupCreateRequest`、`projects.services.approve_create_request`）；`reviews.panels.pending_create_requests()` 只把它摆上评审页 |
| 资格的授予与撤销 | `accounts.services.set_qualification` 与后台批量动作；`reviews.permissions` 只判定 |
| 消息的写入/撤回与渲染 | `notices`（`notify_preliminary_task`／`notify_review_task`／`clear_review_task_messages`／`notify_review_result`）；reviews 只调用 |
| 审计落库 | `core.audit.record_audit` |
| 受保护件的存储口径与取件响应 | `core.storage`（uuid 落盘名）/ `core.downloads.serve_file` |
| 项目组可见性的项目组侧（staff／成员） | `projects.permissions.can_view_group`；评审只提供 `has_review_claim` 这一支 |
| 项目书本体的下载 | `projects.views.group_proposal_download` |

**依赖方向**：`reviews → projects` 在模块加载期就成立（`models.py` 的 `ProjectGroup` 外键、`views.py` 的 `can_view_group`）；`notices` 在加载期被 reviews 依赖（`services.py`）。**反向依赖只有一条是加载期的**：`accounts/admin.py` 在模块级 `from reviews import lifecycle`（两个资格名册要取 `STAGE_*` 常量）；其余都在函数体内（`projects.permissions.can_view_group` → `reviews.permissions.has_review_claim`，`projects.views.group_detail` → `reviews.panels`，`accounts.views.member_home` → `reviews.panels`）。再加反向的模块级 import 之前，先确认不会成环。

**下游消费者**：`projects`（送审入口、详情页评审区块、可见性一支）、`accounts`（成员中心请假面板、身份清单、后台名册的「手上待办」列）、`notices`（`Message.submission` 外键、任务消息与结果消息的取数）、`core.registry`（`ReviewsConfig.ready()` 注册 `reviews:queue` 入口）。

## 2. 关键接口与失败模式

服务层与抽签（写操作一律自带事务与审计；错误一律是 `ReviewError`，`projects.views.group_submit_review` 与 `reviews.views` 把它翻成 `messages.error`）：

| 入口 | 语义 | 前置条件 | 失败模式 |
|---|---|---|---|
| `services.submit_for_review` | 开新一轮，落到 1 名初审人 | `review_type` 在 `REVIEWER_QUOTA` 里；`group.proposal` 非空；该组没有未结束轮次；初审候选 ≥1；评审候选（**排除刚抽到的初审人**）≥ 配额 | `ReviewError`：未选类型／没项目书／上一轮未结束（提示第几轮）／「没有可用的初审人…」／「可用的评审人不足 N 人…」；全程在事务内，拒绝无副作用 |
| `services.submit_verdict` | 交一张任务卡（两道关共用） | 任务是本人的；`decision` 合法；任务仍 `pending`；轮次仍停在这一关 | `ReviewError`：「这不是分配给你的…任务」／「请选择…决定」／「已经处理过了」／`StageRules.closed_refusal`；初审通过但池子不够时**整次回滚**（结论不落库、任务仍在初审人手上） |
| `services._settle_submission` | 汇总本轮结论并在通过时归档（**私有**，由 `submit_verdict` 在父行锁内调用） | 调用方必须已持有 `ProjectSubmission` 行锁 | 不抛；非 `pending` 或有 `pending` 任务时原样返回（因此可被重试、幂等） |
| `services.override_review` | 超级评审一票敲定 | `override_blocker()` 返回 `None`；`decision` 合法 | `ReviewError("无法行使超级评审权：%(reason)s。")` |
| `services.reassign_task` | 把待处理任务原地换人（Admin 与服务唯一入口） | 任务 `pending`；轮次未走过这一关；新人不等于旧人、不是提交人/本组成员；新人未持有本轮任何任务；人在 `eligible_holders` 里 | `ReviewError`，文案按阶段取自 `lifecycle.STAGES[stage]`（`swap_not_pending`／`swap_phase`／`swap_holds` 等） |
| `services.set_reviewer_leave` | 登记或调整本人/他人的未结束窗口 | `may_receive_tasks(reviewer)`（超级评审不接任务，不在此列）；`ends_at > starts_at` 且 `ends_at` 在未来 | `ReviewError`：无资格／时间不合法 |
| `services.clear_reviewer_leave` | 取消未结束窗口 | 至少有一个未结束窗口 | `ReviewError("当前没有可取消的请假。")` |
| `draw.eligible_holders` / `ensure_pool` / `draw_tasks` | 「谁可以接手这一关」的唯一实现；候选不足即拒（附请假人数） | 传 `submission` 时排除本轮**两道关**的全部持有人 | `ensure_pool` 抛 `ReviewError`（「可用的%(role)s不足 N 人（另有 M 人请假）…」） |

判定与只读（不写库、不抛给用户的异常）：

| 入口 | 语义 | 失败模式 |
|---|---|---|
| `selectors.override_blocker` | 超级评审不能敲定这一轮的**原因**，可以时返回 `None` | 不抛；队列页据此标注、详情页据此决定是否给表单、服务据此拒绝 |
| `selectors.can_override_review` | `override_blocker(...) is None` 的布尔包装 | 不抛 |
| `selectors.pending_task_summary` / `PendingTasks` | 「手上还有多少活」的唯一口径（按阶段计数，只算 `pending`，**不扣请假**） | 不抛；当前没有生产调用点，见 §6 |
| `selectors.open_leave_for` | 某人还没结束的请假窗口（没有则 `None`） | 不抛 |
| `permissions.can_open_queue` | 「评审」入口与队列页门槛：三种资格任意一种**或管理员** | 纯布尔 |
| `permissions.has_review_qualification` / `qualifies_for_stage` / `may_receive_tasks` / `has_review_claim` | 资格与「凭评审身份能否看这一组」 | 纯布尔 |

视图与 URL（`config/urls.py` 挂在 `member/reviews/` 下，英文加 `/en/` 前缀）：

| 入口 | 语义 | 前置条件 | 失败模式 |
|---|---|---|---|
| `reviews:queue` → `views.review_queue` | 队列页（GET） | `can_open_queue` | 未登录 302 到登录页；无资格 **403** |
| `reviews:complete` / `reviews:preliminary_complete` → `views.complete_task` | 交卷（POST）。两条路由指向同一视图：用哪套门槛与表单**不由路由决定，而由任务自己的 `stage` 决定** | 该关资格；`task.reviewer_id == request.user.pk` | GET **405**；无资格或不是本人 **403**；任务不存在 **404**；领域拒绝 → 302 + flash |
| `reviews:override` → `views.override_submission` | 一票敲定（POST） | `is_super_reviewer` | GET **405**；非超级评审 **403**；领域拒绝 → 302 + flash |
| `reviews:set_leave` / `reviews:cancel_leave` | 本人请假登记/取消（POST） | `has_review_qualification`（门槛较宽） | GET **405**；无资格 **403**；服务层再按 `may_receive_tasks` 拒绝（超级评审不接任务）→ 302 + flash |
| `reviews:annotated` / `reviews:archive_download` | 批注版／归档件取件（GET） | 已登录；`projects.permissions.can_view_group` | 未登录 302；不可见 **403**；任务没有批注版 **404**；文件不在盘上 **404**（`serve_file` 接住，不是 500） |

拒绝的两种形态是刻意分开的：**门槛类**（谁有资格、任务是不是你的、方法对不对）走 `core.permissions.require`／`PermissionDenied`，是 403；**业务类**（轮次已过站、池子不够、请假时间不合法）由服务层抛 `ReviewError`，视图翻成 flash 后重定向——浏览器拿到的是 302，不是 4xx。

## 3. 状态与不变量

### ProjectSubmission（一轮送审）

| 字段 | 说明 |
|---|---|
| `group` + `round` | 轮次号**组内唯一**（`unique_group_submission_round`）；送审时算「当前最大轮次 + 1」。`group` 是 `PROTECT`——轮次记录必须指向真实存在的项目组 |
| `status` | 四个取值只在 `lifecycle` 里定义；模型上的同名常量是别名。默认 `preliminary_pending` |
| `review_type` | 决定 `required_reviewers`；`blank=True, default=""` 是给升级前的老轮次留的——**空值回退 `DEFAULT_REVIEWERS`（2 人）**，且没有补填入口 |
| `submitted_by` | 提交人（`PROTECT`）；抽签与超级评审的利益冲突判定都读它 |
| `submitted_at` / `decided_at` | `decided_at` 只在迁移表里 `stamps_decided_at=True` 的事件上打点——**初审通过不打**（那一轮还没结论），初审打回、评审汇总、一票敲定都打 |
| `OPEN_STATUSES` | `(preliminary_pending, pending)`，「本轮还在进行吗」的唯一判据 |
| `required_reviewers` | `REVIEWER_QUOTA.get(self.review_type, DEFAULT_REVIEWERS)`——配额表的唯一出口 |

### ReviewTask（任务卡：初审一道关、评审一个评审团）

| 字段 | 说明 |
|---|---|
| `submission` / `stage` | `submission` 是 `CASCADE`：删整轮即删掉它的任务（删除的单位就是整轮）。`stage` 决定这条任务用哪一关的口径（`lifecycle.STAGES[stage]`） |
| `reviewer` | `PROTECT`；资格按 `STAGES[stage].qualification` 取 |
| `status` | 字段只存中性取值 `pending`／`completed`／`released`；阶段化的叫法（待初审／已初审／待评审／已完成）由 `status_label` 按 `(stage, status)` 从 `TASK_STATUS_LABELS` 取 |
| `decision` / `comment` | 两道关共用同一对取值（`approve`／`revise`） |
| `annotated_file` | 只有评审阶段会填（初审给的是理由，不是稿子；表单也不给这个字段）；存储 `private_storage`，落盘名 `neutral_upload_to("review_annotations")`（uuid） |
| `is_override` | 该行来自超级评审的一票决定；CHECK 约束保证它只能出现在 `review` 阶段 |
| `Meta.ordering` | `("status", "stage", "-assigned_at", "-id")`——**详情页「评审人 1/2/3」的编号取的是这个顺序下的 `forloop.counter`**，改排序会改掉谁排在前面 |

### ArchivedProposal（批注版归档）

`group`／`submission`／`source_task` 全是 `PROTECT`（已归档的轮次删不掉），`file` 落在 `protected_media` 的 `review_archives` 下。一行对应「实际传了批注版且结论为通过」的任务：只写文字的人不产生行，原项目书从不复制进来。行在轮次转 `approved` 时一次写成，之后不可变。

### ReviewerLeave（评审人请假）

| 字段 | 说明 |
|---|---|
| `reviewer` | `PROTECT`；请假**不修改** `User.is_reviewer`／`is_preliminary_reviewer`，只是抽签时跳过 |
| `starts_at` / `ends_at` | 窗口；`ends_at` 是**开区间端点**（该时刻即视为在岗）。恢复靠时间自己走完——**没有定时任务、没有要回滚的状态** |
| `reason` / `created_by` | 事由；首次登记人（本人自助为自己，管理员代登记为该管理员） |
| `state` / `state_label` | 现算的三种状态：未开始／请假中／已结束（没有存储字段） |

### 不变量

- **`lifecycle.transition()` 是 `ProjectSubmission.status` 的唯一写入点**。调用方先用 `transition_refusal()` 拿到给用户看的话，真从非法状态撞进来抛 `IllegalTransition`（代码错误，不是用户错误）。
- 三条唯一约束：`ProjectSubmission` 的 `(group, round)`；`ReviewTask` 的 `(submission, reviewer)`（**一人一轮一席**）与 `(submission) WHERE stage='preliminary'`（每轮恰好一条初审；**允许零条**——升级前的老轮次没有）。
- `ReviewTask` 上另有 CHECK `override_is_review_stage_only`（`is_override=False OR stage='review'`）。
- `ArchivedProposal` 上 `source_task` 唯一——归档幂等的依据。
- `ReviewerLeave` 上 CHECK `ends_at > starts_at`；「一人同时至多一个未结束窗口」**不是数据库约束**（PostgreSQL 索引谓词必须 immutable，`now()` 不是），规则住在 `services.set_reviewer_leave`。
- **`RELEASED` 是终态**：不再计入待办、不能再提交（`submit_verdict` 对非 `pending` 一律拒绝），但行保留——名单上仍看得出曾请过谁。
- **`REVIEWER_QUOTA` 是配额的唯一判定点**：竞赛立项／省赛／国赛 3 人，大创中期／结题 2 人，大创立项 1 人。加一个 `REVIEW_TYPE_CHOICES` 选项必须同时在配额表里加一行，否则 `required_reviewers` 会悄悄回退到 2（`ReviewTypeQuotaTests.test_every_choice_has_a_quota` 盯着这条）。
- 送审类型是**平台内标签**，刻意不与 `competitions.Competition` 建外键。
- 同一项目组同时只能有一个未结束轮次，判据是 `OPEN_STATUSES`（不是 `status == "pending"`——那现在只表示「已过初审、正在评审」）；判定在 `ProjectGroup` 行锁内进行。
- 项目书**只存一份**在 `ProjectGroup.proposal`；评审侧任何表都不复制它。

**唯一真相源速查**

| 问题 | 唯一答案 |
|---|---|
| 状态能这么走吗、给用户看什么话 | `lifecycle.TRANSITIONS` + `transition_refusal()` / `transition()` |
| 这道关的措辞、要哪个资格、停在哪个状态、审计 action 叫什么 | `lifecycle.STAGES` 的一条 `StageRules` |
| 本轮还在进行吗 / 这一关现在轮得到吗 | `OPEN_STATUSES` / `lifecycle.stage_is_open()` |
| 本轮需要几名评审人 | `REVIEWER_QUOTA` + `ProjectSubmission.required_reviewers` |
| 谁可以接手这一关的任务 | `draw._eligible_pool()`（`eligible_holders()` 是它的公开入口） |
| 这个超级评审能不能敲定这一轮 | `selectors.override_blocker()` |
| 本轮的初审任务是哪条 | `models.preliminary_task_of()`（现查，**不用 `submission.tasks` 的缓存**——那一行会被改派、交卷、释放） |
| 某人的待办数字，以及它的措辞（`parts`／`headline`） | `selectors.PendingTasks` / `pending_task_summary()` |

## 4. 数据流与时序

### 送审 → 初审

1. 视图 `projects:group_submit_review`：`_require_group_manager`（联系人本人或管理员）→ `SubmissionForm`（必选类型）→ 调 `submit_for_review`。
2. 服务先拒两种情况：类型不在 `REVIEWER_QUOTA`、`group.proposal` 为空。
3. 进入事务，**先锁 `ProjectGroup` 行**。为什么：不锁的话两次并发提交会同时通过「没有未结束轮次」的检查，又各自算出同一个轮次号，撞上 `(group, round)` 唯一约束——把 500 留给用户。
4. 查未结束轮次，有则拒（提示是第几轮）。
5. 抽 1 名初审人（候选不足即拒）。
6. **容量预检**：评审池（排除刚抽到的初审人）必须够 `REVIEWER_QUOTA[review_type]` 人。预检是「不开出一轮谁也推进不了的送审」的那道闸——真开出来，联系人被单轮次约束挡着、初审人也通不过，只能等管理员或超级评审来收场。抽人本身仍留到初审通过时。
7. 轮次号 = 当前最大轮次 + 1；建 `ProjectSubmission`（默认 `preliminary_pending`）与 1 条初审 `ReviewTask`。
8. 写「待初审」消息（`notices_services.notify_preliminary_task`，**在事务内**——回滚时消息一起消失）。
9. 出事务后写审计 `reviews.submission.create` 与日志。

### 初审交卷（两道关共用 `submit_verdict`）

10. 初审人在项目组详情页提交 → `reviews:preliminary_complete` → `submit_verdict`。
11. 事务外先校验「是不是分配给你的」「结论取值合不合法」；事务内**先锁 `ProjectSubmission` 父行，再锁 `ReviewTask` 行**。
12. 拒绝条件：任务已不是 `pending`（已交或已被释放）、轮次已不在 `preliminary_pending`。
13. 写 `completed` + `decision` + `comment` + `completed_at`；撤掉本人的任务消息（消息只负责「有事等你」，历史归评审页）。
14. **通过** → `_open_review_stage`：`transition(PRELIMINARY_APPROVED)` 把轮次推到 `pending`（**不打 `decided_at`**），随即在同一次事务里按 `required_reviewers` 抽人。此刻排除名单已经含本轮初审人（`submission.tasks` 两道关一起算）——一个人既放行又评审，等于让同一份意见在一轮里占两个位置。抽不齐就 `ReviewError`，**整个事务回滚**：结论不落库、初审任务仍待处理，初审人可以在有人空闲后原地重试。抽齐则每条评审任务各写一条「待评审」消息。
15. **打回** → `transition(PRELIMINARY_REVISED)` 到 `needs_revision`，打 `decided_at`，一个评审人也不分配。
16. 轮次一旦有结论（打回，或评审阶段汇总出结果），`_notify_result_if_settled` 在事务内给项目组联系人写结果消息（`get_or_create` 幂等）；审计 `reviews.preliminary.complete` 在事务提交之后写。

### 评审交卷 → 汇总 → 归档

17. 评审人交卷走同一条 `submit_verdict`（锁序、校验、审计形状完全相同）；`annotated_file` 只有这一阶段会落库。
18. `_settle_submission` **在父行锁内**汇总：轮次不是 `pending` 就返回；还有 `pending` 任务就返回；有人 `revise` → `needs_revision`，否则 `approved`；两者都打 `decided_at`。
19. 通过 → `_archive_annotated_proposals`：对每条「`completed` 且 `approve` 且有附件」的任务，`get_or_create(source_task=…)` 后把文件字节复制进 `ArchivedProposal`。`source_task` 唯一约束 + `get_or_create` 让重试幂等；只写了文字意见的评审人不产生归档行。
20. 给联系人写结果消息（一轮一条，`get_or_create`）。

**为什么并发审结必须锁父行**：汇总要读本轮**其他**任务。只锁自己那条任务，两个同时交卷的人会各自看到对方仍是 `pending`，双双返回、谁都汇总不了，轮次永久卡在「评审中」。

**打回之后页面指路哪一份意见**：`needs_revision` 的轮次在详情页区分两种来路——走完评审被打回 → 指路「评审意见」；**初审直接打回**（本轮从未分配评审人）→ 指路「初审意见」，不让项目组去找不存在的评审意见。

### 超级评审一票敲定

21. 队列页或详情页 → `reviews:override` POST → `override_review`。
22. 锁父行 → 用 `override_blocker()` 再判一次（与页面显隐、队列标注同一个函数）→ 建一条 `is_override=True`、`completed` 的评审任务（结论、意见、批注版都挂在它上面）→ 把所有 `pending` 任务（**含初审**）批量置 `released` → `transition(OVERRIDE_APPROVED/REVISED)` → 通过则归档 → 撤掉本轮全部待办消息 + 写结果消息。
23. **刻意不走 `_settle_submission`**：那条汇总回答「是不是每个评审人都通过了」，会把某个普通评审人先前的「需修改」顶回去——而那正是这条路径要做的决定。因为父行锁已经排除了并发交卷，释放用的批量 `UPDATE` 不需要再加逐行锁。
24. 「进行中」包含初审中：一轮还压在初审人手上时照样可以敲定，这是初审人失联时的另一条出路。

### 改派（管理员）

25. `reassign_task`：锁父行 → 锁任务行（**与交卷同一锁序**）→ 任务 `pending` 且轮次未走过这一关 → 依次拒绝：同一个人、提交人、本组成员、已持有本轮任一任务、不在 `eligible_holders` 里 → 原地改 `reviewer`（不删行、不重新判结论、不触碰归档）→ 消息从旧持有人撤走、给新持有人写一条。
26. 这是评审人／初审人失联或事后发现利益冲突时**唯一**的补救路径；没有它，该轮会永久停在「初审中」或「评审中」。结论一旦落下就不再允许换人——换人等于把结论、意见与批注文件记到别人名下。

**事务边界**：状态迁移、任务创建/改派、消息、归档都在同一个 `transaction.atomic()` 里；审计在事务**提交之后**写，所以回滚不会留下假审计。

## 5. 错误处理与诊断

**领域异常 → 页面提示**：`exceptions.ReviewError` 把下层（抽签、查询）与服务层的拒绝统一成一种错误，视图一律 `messages.error(request, str(exc))` 后重定向；`projects.views.group_submit_review` 与 `ReviewTaskAdmin.save_model` 同样处理。`_advance()` 先问 `transition_refusal()`，不允许就用那句话抛 `ReviewError`；`IllegalTransition` 是绕过这个前置检查才会撞到的代码错误，从不面向用户。

**审计 action**（一旦发布不再改，历史记录要保持连续）：

| action | 触发 |
|---|---|
| `reviews.submission.create` | 送审成功 |
| `reviews.preliminary.complete` / `reviews.assignment.complete` | 初审／评审交卷（`StageRules.submit_action`，字符串沿用合并前的值） |
| `reviews.preliminary.reassign` / `reviews.assignment.reassign` | 改派（`StageRules.reassign_action`） |
| `reviews.submission.override` | 超级评审一票敲定 |
| `reviews.leave.set` / `reviews.leave.clear` | 经服务的请假登记／取消 |
| `reviews.leave.admin_save` | 后台直接新增／修改请假 |
| `reviews.submission.delete` | 后台删整轮（`target=None`，标识全在 `detail` 里——对象已经不在了） |

**权限拒绝是日志事件不是审计**：`core.permissions.require(request, predicate, event, **fields)` 在拒绝时记一条 warning 再抛 `PermissionDenied`。本模块用到的 event：`reviews.permission.denied`（附 `reason=no_queue_access`／`no_preliminary_qualification`／`not_super_reviewer`）、`reviews.download.denied`（附 `group_id`、`what=annotated|archived`）。**一处例外**：`views.complete_task` 判「这不是分配给你的任务」时直接 `raise PermissionDenied`，**不留日志**——排查「谁在被拒」时这一支是静默的，别以为所有 403 都经 `require`。另有几处 info 日志：`reviews.queue.view`、`reviews.annotated.download`、`reviews.archive.download`、`reviews.proposal.archive`；服务层日志统一带 `extra={"request_id": ...}`。

**`override_blocker()` 的「返回原因」写法**：它返回**不能行使的具体原因**（`None` 表示可以），而不是布尔。队列页拿它给不可行使的轮次标注「不可行使 · 你是本轮的提交人」、详情页拿它决定给不给表单、服务层拿它拼拒绝话术——一处判定，三处不各写一份。原因按顺序是：没有超级评审资格／本轮已经出过结论／你是本轮的提交人／你是本项目组成员／你在本轮已有任务（初审的提示语按「待提交」与「已交」分成两句）。这个写法值得照抄到别处：**判定函数把「为什么不行」带回来，界面才解释得清楚**。

**匿名口径落在三处**（评审的硬约束，任何一处漏掉都会从存储层或页面反向识别出评审人）：

| 位置 | 落实方式 |
|---|---|
| 落盘名 | `neutral_upload_to(...)` 换成 uuid（`review_annotations`／`review_archives`）；原文件名会带人名、组名，还会跟着备份与运维的 `ls` 扩散出去 |
| 下载头 | `views._annotated_filename()` 现拼中性名「批注版项目书_R{轮次}{扩展名}」，`as_attachment=True`；账号、姓名都不出现 |
| 页面 | 模板只渲染「初审」「评审人 N」「超级评审」；账号只在服务端可见（`ReviewTaskAdmin` 的 `reviewer` 列、审计与运行日志）——日志里 `reviewer=` 记的是账号，页面从不出现 |

取件一律经视图（`FileResponse` 由 `core.downloads.serve_file` 生成），不走 Nginx——`protected_media` 刻意不在 `mediafiles/` 之下，没有任何 HTTP 路径能直接取到。批注版与归档件随 `Content-Digest` 与 `X-Checksum-SHA256` 送出（`ReviewTask.digest_field`／`ArchivedProposal.digest_field` 由 `core.hashing.FileDigestMixin` 维护）；归档件是源任务那份的副本，**两份指纹相同**——对不上就说明归档之后被动过。

**为什么删除的单位是「整轮」**：Django 的级联检查会拿被级联的任务去问任务自己的 admin，所以 `ProjectSubmissionAdmin.get_deleted_objects` 必须豁免「任务不能增删」那两项权限，否则连整轮也删不掉；反过来，真让人删掉单条任务，会**悄悄改变该轮所需的评审人数**（名单少一个人，汇总就等不到他）。

**诊断入口**：一个轮次的全貌在项目组详情页（初审一行、超级评审一行、其余按 `评审人 N` 编号），任务与轮次的原始记录在 Admin 的「项目评审」三屏 + 请假一屏；「这一票为什么不能投」在队列页的标注里。

## 6. 测试要点与已知限制

### 测试

| 文件 | 钉住什么 |
|---|---|
| `tests/test_submission.py` | 开轮次的条件：类型必选、要有项目书、单轮次（初审中也算未结束）、初审候选与评审容量预检、轮次号推进、老轮次回退 2 人、配额表覆盖所有选项 |
| `tests/test_preliminary.py` | 初审关卡：一对一、与评审共用结论取值、通过才抽人（并排除初审人自己）、打回不抽人、池子在提交后缩水时整次回滚、审计、页面上的匿名与打回指向初审意见、改派初审 |
| `tests/test_verdicts.py` | 汇总规则（全员通过／任一需修改）、汇总与调用方无关、批注版与归档（只归档上传者、指纹一致、幂等、需修改不归档）、两个下载入口的权限 |
| `tests/test_review_pages.py` | 谁能看到什么：队列 403、详情页匿名、初审只占一行且编号只数评审任务、表单 `multipart`、完整链路走视图、管理员队列里的建组申请待办 |
| `tests/test_reassignment.py` | 改派规则（已交／已判／同一人／提交人／成员／已持有任务／无资格／停用／请假逐一拒）与后台形态（只读账号不能改派、单条任务不能删） |
| `tests/test_leave.py` | 请假窗口：未开始不排除、过期自动恢复、两种抽取都生效、请假人数提示只算有资格的人、重复登记改同一个窗口、表单与后台 |
| `tests/test_super_reviewer.py` | 一票敲定：不许被普通评审人的「需修改」顶回、释放等待中的任务、初审中也能敲、三种利益冲突、`override_blocker` 的每种原因、队列页标注与表单显隐 |
| `tests/test_reminders.py` | 消息的去向（notices 侧的口径）：分配时写、交掉/释放/改派时撤、结论给联系人；登录 flash 与成员中心待办卡片已撤 |
| `tests/test_admin_rounds.py` | 删整轮（连带两道关）与「单条任务不能删」两条相反的规则同时成立；归档过的轮次删不掉 |

夹具分两处：`tests/factories.py` 只造对象（用户、项目组、上传件），`tests/base.py` 给每个类一份临时 `MEDIA_ROOT` 与 `PRIVATE_MEDIA_ROOT`（两个根都要覆盖，受保护件不在 `MEDIA_ROOT` 之下），并把「送审→过初审→交卷」的几步收成 `_open_round`／`_pass_preliminary`／`_submit`／`_approve_round`。**具体的人一律留在各类的 `setUp` 里、不进基类**：一轮抽到谁由候选人数决定，基类塞一套夹具是让抽签断言变脆的最快办法。

### 已知限制 / 当前不支持的情况

- **送审后项目组侧没有撤回入口**：本轮只能由初审打回、评审汇总、超级评审敲定三种方式出结论；确有需要时管理员在后台删整轮（连带任务，写审计）。
- **评审名额完全由送审类型决定**：没有「本轮临时加人／减人」的入口（`ReviewTaskAdmin` 禁止新增），改派只能换人、不能补席位。
- **没有「拒绝任务」这个动作**：评审人失联只能由管理员改派或超级评审收场。
- **一票敲定通过时的归档只收「已完成且通过」的批注版**：此前判过「需修改」的普通评审人即便上传了批注版，也不进归档（`_archive_annotated_proposals` 的过滤条件就是 `completed` + `approve`）。`docs/architecture/reviews.md` 里「会一并收走此前普通评审人已上传的批注版」的说法比代码宽，以代码为准。
- **`ReviewerLeaveAdmin` 不经过 `set_reviewer_leave`**：后台可以直接新增/编辑请假，于是「一人至多一个未结束窗口」「有评审资格」「`ends_at` 在未来」这三条都不生效，只剩数据库 CHECK（`ends_at > starts_at`）兜底；`list_editable` 改时间同样只补一条 `reviews.leave.admin_save` 审计。
- **「一人一个未结束窗口」不是数据库约束**：规则只在服务层，靠 `select_for_update` 锁住已有的未结束窗口来收窄竞态；这个人本来就没有窗口时（并发首次登记）两边都锁不到行，理论上可以留下两个重叠窗口。影响有限——抽签排除按「任一窗口命中即排除」，面板只显示最近的那个。
- **升级前留下的老轮次**：`review_type` 为空（回退 2 人）且**可能没有初审任务**（唯一约束允许零条），所以 `preliminary_task_of()` 的调用方都要处理 `None`，模板也要能少渲染一行；这两样都无法补填。
- **`pending_task_summary()` 目前没有生产调用点**：登录提醒与成员中心待办卡片已撤，队列页的数字改用 `queue_context` 分档后的长度。它仍是「待办数字」的口径定义处，但文档里「队列页仍用它报数」的说法已经过期。
- **批注文件的正文/属性不做检查**：平台只保证文件名与下载头不含身份，文件内容里自带姓名只能靠上传时的提示（「请勿在文件属性中保留可识别个人身份的信息」）。
- **详情页的「评审人 N」是位置编号**：按 `ReviewTask.Meta.ordering` 下的遍历顺序给号，超级评审那一票也占一个序号位置，所以它不是稳定标识，只是「这一轮的第几份意见」。
