# 接口规格

> 谁跟谁之间的契约，分三层：**A. 页面与 HTTP**（地址、方法、门槛、失败形态）、
> **B. 跨应用公开函数**（各 app 对外的判定 / 只读 / 写命令）、**C. 数据模型与迁移**
> （跨模块依赖的字段、约束与旧数据处置）。
>
> 表结构与模块内部规则**不在这里**——那是各 app 的 `README.md` 的事（见 [README.md](README.md)）。

**什么时候看**：加一个页面或地址、跨 app 调一个函数、改一个被别处依赖的字段或约束。

---

## A. HTTP 契约

### A.0 共同口径

- **地址即语言**：中文地址不带前缀，英文加 `/en/`；后台 `/admin/` 不在双语范围内（见 [glossary.md](../glossary.md)）。
- **写操作一律 POST + CSRF**。**表单页**失败时重渲染 200、成功 302；**动作端点**（`@require_POST`）不论成败都 302（PRG + flash）。下表**标 POST 的就是动作端点**（收到 GET 会 405）；未标的是「GET 显示表单 + POST 提交」的页面或纯展示页。
- **路径写法**：同一入口的多个动作写成「`/a/` `/b/`」时，后一个是与前一个**同前缀**的兄弟路径（如 `/member/profile/avatar/` `/delete/` 指 `/member/profile/avatar/delete/`）。
- **拒绝的四种形态**——下表每一行的失败形态由「这一行的门槛」加这张表推出，只有例外才单独标注：

  | 情形 | 形态 |
  |---|---|
  | 未登录 | 302 到 `accounts:login`（带 `next`） |
  | 已登录，但缺资格／不是本人／缺对象级权限 | **403**（门槛经 `core.permissions.require`，或视图里直接 `PermissionDenied`） |
  | 对象不存在、或不属于当前上下文 | **404** |
  | 对 POST-only 视图发 GET | **405** |

- **业务拒绝不是 4xx**：服务层抛领域异常（`JoinRequestError` / `ReviewError` / `GroupManagementError` 等），视图翻成 flash 后 302 回列表页——浏览器拿到的是 302，不是 4xx。
- **未改密账号**：`must_change_password=True` 时，除改密页与登出外的一切路径都 302 回改密页（`config.middleware`，连 `/admin/` 也不放行）。
- **越权取件的 403 是否留痕**：多数经 `require` 记一条 warning；已知两处**裸抛、不留日志**——`projects:group_proposal_download` 与 `reviews:complete`（「不是分配给你的任务」）。排查越权尝试时记得这两支是静默的。

### A.1 公开门户（无需登录）

| 路径 | 页面 |
|---|---|
| `/` | 首页：社团影像切换区（HomeSlide，同屏单帧切换）+ 最新公开公告 + 公开内容入口 |
| `/about/` | 社团简介快捷地址（读取 ContentPage slug=about；未发布时显示空状态，不返回 404） |
| `/pages/` | 更多页面：已发布的通用 ContentPage 清单（不含 slug=about，首页「了解社团」入口） |
| `/pages/<slug>/` | 通用公开内容页（仅已发布的 ContentPage 可访问，未发布 404） |
| `/awards/` | 历年获奖列表：一个搜索框匹配姓名／指导老师／赛事／层级／级别写法／年份，每页 10／20／40 可选；登录成员在此还能勾选条目打包下载证书、进入添加页 |
| `/showcase/` | 成员风采 |
| `/notices/` | 公开公告列表（一次列全，不分页——社团规模够用；页面上标了总条数） |
| `/notices/<id>/` | 公告详情 |
| `/login/` `/logout/` | 登录 / 登出 |

### A.2 成员界面（需登录）

| 路径 | 方法 | 页面 | 门槛 |
|---|---|---|---|
| `/member/` | | 成员首页：身份／评审与初审资格 + 社团概览（仅管理员与联系人可见）+ 操作面板（注册表渲染） | 登录 |
| `/member/notices/` | | 「我的消息」：内部通知 + 仅联系人可见通知的列表/详情 | 登录（按受众过滤，未命中 404） |
| `/member/notices/read-all/` | POST | 「全部已读」：把当前可见的未读一次标掉 | 登录 |
| `/member/notices/message/<id>/go/` | | 事件消息的中转：先标已读、再跳到帖子锚点/项目组等目标页 | 登录（限收件人本人，别人 404） |
| `/member/profile/` | | 个人信息：资料表单 + 头像与「当前身份」（只读）+ 个人图册 | 本人 |
| `/member/profile/<id>/` | | 其他成员的只读资料：头像、姓名、院系、身份、图册及明确公开的联系方式（不显示学号/邮箱） | 登录成员（目标须 `is_active`） |
| `/member/avatar/<user_id>/` | | 头像文件的取件口（受保护件，只能经此取） | 登录即可 |
| `/member/gallery/<id>/file/` | | 图册图片的取件口（同上） | 登录即可（他人的图 404） |
| `/member/profile/avatar/` `/delete/` | POST | 上传／更换／删除头像 | 本人 |
| `/member/profile/gallery/` | POST | 往个人图册加图（可一次选多张） | 本人 |
| `/member/profile/gallery/<id>/move/` `/layout/` `/delete/` | POST | 上移下移／改排布／删除一张 | 本人（他人的图 404） |
| `/member/password/` | | 修改密码 | 本人 |
| `/awards/new/` | | 添加获奖记录（判重拦下重复项） | 登录成员 |
| `/awards/certificates.zip` | POST | 勾选若干条记录，打包下载其中的获奖证书（一次最多 100 条） | 登录成员 |
| `/member/space/`、`/member/space/boards/<id>/` | | 社团空间与板块帖子流（置顶优先、其余按时间倒序） | 登录成员 |
| `/member/space/boards/<id>/posts/new/`、`/member/space/posts/<id>/edit/` | | 发帖、编辑本人帖子 | 登录成员 / 作者 |
| `/member/space/posts/<id>/comments/`、`/delete/` | POST | 评论、删除帖子（删帖级联删评论） | 登录成员；删自己的帖或管理员删任意帖 |
| `/member/space/comments/<id>/delete/` | POST | 删除一条评论（软删除） | 评论作者或管理员 |
| `/member/space/images/<id>/` | | 帖子图片本身（随机文件名落盘，经此路由校验后才发出） | 登录成员 |
| `/member/space/posts/<id>/pin/` | POST | 置顶 / 取消置顶 | 管理员 |
| `/member/space/boards/create/`、`/boards/<id>/delete/` | POST | 前端创建板块或删除空板块 | Django 超级管理员 |
| `/member/projects/` | | 项目组列表：**登录即列全部**（任何身份都一样）；`?q=` 搜索、`?mine=1` 只看自己参与的组 | 登录 |
| `/member/projects/create/` | | 申请创建项目组（名称与描述必填） | 登录 |
| `/member/projects/<id>/apply/` | | 申请加入项目组 | 登录且非该组成员 |
| `/member/projects/<id>/manage/` | | 管理组：GET 显示各区块，POST 带 `action=` 分派（核申请、移除成员、转让联系人、改组介绍与学院/指导老师） | 该组联系人 / 管理员 |
| `/member/projects/<id>/manage/requests/<req>/<action>/` | POST | 通过/拒绝入组申请 | 该组联系人 / 管理员 |
| `/member/projects/<id>/manage/members/<user>/remove/` | POST | 移除组员 | 该组联系人 / 管理员 |
| `/member/projects/<id>/manage/proposal/` | POST | 上传 / 更新项目书（doc/docx/pdf） | 该组联系人 / 管理员 |
| `/member/projects/<id>/manage/submit/` | POST | 提交项目书审核（选送审类型 + 可选说明） | 该组联系人 / 管理员 |
| `/member/projects/create/requests/<req>/<action>/` | POST | 同意/拒绝创建项目组申请；任一管理员同意即通过，处理完跳回「评审」页 | 管理员 |
| `/member/projects/<id>/` | | 项目组详情：学院与指导老师、成员、项目书、批注版归档、初审与评审状态及历史 | staff / 该组成员 / 本轮初审人 / 被分配评审人 / **该组有进行中轮次时的超级评审**（几支**取并集**，见 [projects.md](projects.md)） |
| `/member/projects/<id>/proposal/` | | 下载当前项目书 | 同上（越权 403，**无日志**） |
| `/member/reviews/` | | 我的评审队列（初审与评审各三档；超级评审另有「全部进行中」；管理员另有「创建项目组申请」） | 初审人 / 评审人 / 超级评审 / 管理员 |
| `/member/reviews/leave/` `/leave/cancel/` | POST | 登记 / 修改 / 取消本人「初审／评审请假」 | 初审人 / 评审人 |
| `/member/reviews/preliminary/<id>/complete/` 与 `/member/reviews/<id>/complete/` | POST | 提交结论（两条路径是**同一个视图**，按任务的 `stage` 选门槛与表单；两条都保留以保住历史链接） | 该任务的初审人 / 评审人 |
| `/member/reviews/override/<id>/` | POST | 超级评审对进行中的轮次直接通过或打回 | 超级评审 |
| `/member/reviews/<id>/annotated/`、`/archive/<id>/download/` | | 下载批注版 / 归档版项目书 | 同项目组详情页的门槛 |
| `/member/competitions/` | | 竞赛列表（所有登录成员可见；联系人可见报名操作） | 登录 |
| `/member/competitions/<id>/register/` | | 为项目组登记竞赛报名（含竞赛组长） | 项目组联系人（仅自己的组）/ 管理员 |
| `/member/competitions/registrations/<id>/edit/` | | 修改报名 | 该组联系人 / 管理员 |
| `/member/competitions/registrations/<id>/withdraw/` | POST | 放弃报名 | 该组联系人 / 管理员 |
| `/member/equipment/` | | 设备列表 + 借用登记 | **项目组成员** / 管理员 |
| `/member/equipment/<id>/borrow/` | | 登记借用单个设备 | **项目组成员** / 管理员 |
| `/member/borrows/` | | 我的借用记录（管理员看全部） | 登录（含已移出组者） |
| `/member/borrows/<id>/return/` | POST | 登记归还 | 本人 / 管理员（**不查项目组归属**） |

> `?mine=1`、`?q=`、`per_page` 这类查询参数的口径在各 app 的 README 里（例如获奖页的 `per_page` 只认 10／20／40，白名单外回落默认）。

### A.3 管理后台

- 起步直接复用 Django Admin：`/admin/` 管理账号、通知、竞赛、设备、项目组、展示内容。
- **「身份管理」分组**（`config/admin.py` 把六张名册从各自的 app 分组里提出来置顶）：

  | 名册 | 行里看得到 |
  |---|---|
  | 管理员 / 评审人 / 初审人 / 超级评审 | 该人的**全部身份**，以及手上有几件待办（评审人、初审人两列） |
  | 项目组联系人 | 他负责的项目组 |
  | 项目组成员 | 他所在的每个项目组，以及在各组里是联系人还是成员 |

  六张名册都是只读的（`core.admin.RoleRosterAdmin`），顶上有一句「这个身份从哪来」。分组的顺序必须与 `core.roles` 的 `sort_order` 一致。
- **用户组（`auth.Group`）的成员直接在组页增删**：这个「组」只用于内部通知的投递范围，既不是项目组，也不是身份名册。组页的「组内用户」是一个穿梭框，保存走 `accounts.services.set_group_members`（整份覆盖、与现状比对后只动真正变了的人、锁组行、真变更才留审计）。
- 账号后台的「权限」区可以逐个发放三种评审资格；**批量**发放走用户列表页的六个动作（授予／撤销 × 三种资格），写入经 `accounts.services.set_qualification`。**没有**「批量授予管理员资格」。
- 评审记录以只读留痕为主，四处例外：请假的两个时间可列表直改、待处理且该轮未判结论的评审/初审任务可改派、**整轮送审可删**（已归档的除外）。写操作都经服务层或留审计。

---

## B. 跨应用公开函数

**规矩**：跨应用只经对方的 `permissions` / `services` / `selectors` 公开函数（模型外键除外）；判定只写在 `permissions`，写命令只写在 `services`。每个函数的前置条件与失败模式见各自 app 的 `README.md`，这里只给**清单与一句话语义**——它是「这个能力该问谁」的索引。

> **横切件不在下表**：`core.audit.record_audit`（写留痕）、`core.downloads.serve_file`（取件响应）、`core.hashing.FileDigestMixin`、`core.storage`、`core.stats` 这些是**每个 app 都可能调**的基础设施，清单与失败模式见 [`core/README.md`](../../core/README.md) §2。

### B.1 判定（谁能做什么）

| 模块 | 函数 | 一句话 |
|---|---|---|
| core | `is_admin(user)` / `require(request, predicate, event, **fields)` | 「谁算管理员」的唯一写法；视图门槛的唯一样板 |
| projects | `is_project_contact` / `is_project_member` | 对象身份：联系人由 `leader` 计算，成员看 `members` |
| projects | `can_manage_group` / `can_view_group` | 管这个组／看这个组（后者是项目组侧与评审侧主张的**并集**） |
| projects | `can_use_equipment` / `can_decide_group_create_requests` | 设备借用门槛；谁能处理建组申请 |
| projects | `contact_group_ids` / `member_group_ids` / `manageable_group_ids` / `groups_visible_to` | 列表与收件范围的四个集合口径 |
| reviews | `is_reviewer` / `is_preliminary_reviewer` / `is_super_reviewer` | 三种资格 |
| reviews | `qualifies_for_stage` / `may_receive_tasks` / `has_review_qualification` / `has_review_claim` | 按阶段取资格、能否接新任务（请假不算）、任一资格、凭任务看某个组 |
| reviews | `can_open_queue` | 「评审」入口与队列页：三种资格任一**或管理员** |
| notices | `public_visible_notices` / `member_visible_notices` | 通知可见性的单点（列表、详情、未读计数共用） |
| discussion | `is_member` / `can_view_space` / `can_create_post` / `can_comment` / `can_edit_post` / `can_delete_post` / `can_delete_comment` / `can_pin_post` | 成员与作者／管理员的分层（`is_member` 被 `content` 在加载期依赖） |
| discussion | `can_create_board` / `can_delete_board` | 只认 Django `is_superuser` |
| content | `can_manage_awards` | 谁能加获奖记录 |
| competitions | `is_competition_manager` / `can_register_group` | 报名权限（后者委托 `can_manage_group`） |

### B.2 写命令（services：事务、审计、领域异常都在这里）

| 模块 | 函数 | 一句话 |
|---|---|---|
| accounts | `set_qualification` / `set_group_members` | 批量授予撤销资格；组员整份覆盖 |
| accounts | `set_avatar` / `clear_avatar` | 头像的写入口（要传**库里那一份** profile） |
| accounts | `add_gallery_images` / `move_gallery_image` / `set_gallery_layout` / `delete_gallery_image` | 图册的四个写入口（合计上限只在第一个里把守） |
| projects | `apply_to_group` / `approve_join_request` / `reject_join_request` | 入组申请与审批 |
| projects | `apply_to_create_group` / `approve_create_request` / `reject_create_request` | 建组申请与审批（任一管理员同意即建组） |
| projects | `sync_group_membership` / `remove_group_member` / `transfer_contact` / `update_group_info` / `update_group_description` | 成员与组信息维护 |
| reviews | `submit_for_review` / `submit_verdict` | 开一轮送审；交一张任务卡（两道关共用） |
| reviews | `override_review` / `reassign_task` | 一票敲定；改派（唯一补救路径） |
| reviews | `set_reviewer_leave` / `clear_reviewer_leave` | 请假窗口的登记与取消 |
| notices | `notify_*` / `clear_review_task_messages` / `sync_mention_messages` / `clear_mention_messages` | 事件消息的写入与撤回（**别的模块只调用，不自己写表**） |
| notices | `mark_read` / `mark_message_read` / `mark_all_read` | 已读回执与全部已读 |
| content | `create_award` | 前台加获奖记录（判重在这里） |
| discussion | `create_board` / `delete_board` / `create_post` / `update_post` / `delete_post` / `set_post_pinned` / `create_comment` / `delete_comment` | 社团空间的写入口（审计的事务边界不统一，见其 README） |
| competitions | `save_registration` / `withdraw_registration` | 报名、修改、放弃（**自己不查截止**，由表单与视图把关） |
| equipment | `create_borrow` / `return_borrow` | 借与还（库存扣减与回补在事务里） |

### B.3 只读（selectors）

| 模块 | 函数 | 一句话 |
|---|---|---|
| accounts | `member_identities` / `gallery_usage` | 「当前身份」清单；图册用量 |
| projects | `groups_led_by` / `groups_of_member` / `search_groups` / `annotate_member_count` | 按人取组；按关键字搜组（会 JOIN `members`/`advisors`，结尾 `distinct`）；给查询集加 `member_count`——**真实**成员数，子查询，不随搜索过滤变小 |
| reviews | `override_blocker` / `can_override_review` / `pending_task_summary` / `open_leave_for` | 一票敲定能不能行使（返回**原因**）；待办数字；未结束的请假 |
| notices | `message_rows` / `unread_message_count` / `message_target_url` | 消息行的现取现算（标题/链接/说明不落库） |
| content | `search_awards` | 获奖搜索（一个关键字扫五个字段 + 年份） |
| discussion | `board_list` / `posts_for_board` / `page_of_post` / `member_directory` | 板块、帖子流与**全站唯一**的「这条帖子在第几页」 |

---

## C. 数据模型与迁移

### C.1 跨模块的字段承诺

这些字段**被别的 app 读**，改动会外溢——改之前先搜引用（各 app README 里有逐字段说明）：

| 字段 | 谁在读 | 承诺 |
|---|---|---|
| `User.is_reviewer` / `is_preliminary_reviewer` / `is_super_reviewer` / `must_change_password` | `reviews.permissions`、中间件 | 资格是用户属性、相互独立；资格**判定**在 `reviews`，这里只存 |
| `ProjectGroup.leader` / `.members` | `reviews`、`competitions`、`equipment`、`notices`、`core.stats` | 联系人的唯一真相源；联系人恒为成员（**靠代码保证，没有数据库约束**） |
| `ProjectGroup.proposal` | `reviews`（各轮次共用同一份） | 项目书只存这一份，评审侧不复制 |
| `Notice.scope` / `visible_groups` | `notices.visibility`、成员侧过滤 | 三个取值；`internal` 才需要用户组 |
| `Message.kind` + 五个引用外键 | `notices.selectors` | 加一个 kind 要同时改三处（见其 README） |
| `ReviewTask.stage` / `.status` / `.decision`、`ProjectSubmission.status` | `reviews.lifecycle`、`panels`、模板 | 状态只能经 `lifecycle.transition()` 写；「还在进行吗」只能问 `OPEN_STATUSES` |
| `AuditLog.action` | 运维、排查 | **字符串一旦发布就不再改**，历史要连续 |

### C.2 约束（对外承诺，改名要动迁移）

- `accounts`：`Profile.student_id` 唯一（空值落 NULL——**空值语义是 NULL，不是空串**）。图册的「每人合计 100 MB」**不是**约束，只在 `services.add_gallery_images` 一条路上把守。
- `projects`：`unique_project_advisor_slot`（`(group, sort_order)`）+ `CHECK(sort_order < 3)`＝每组至多 3 位指导老师；两张申请表各一条 `WHERE status='pending'` 的部分唯一。
- `reviews`：`unique_group_submission_round`、`unique_submission_task_reviewer`、`(submission) WHERE stage='preliminary'`、`unique_archived_proposal_task`、`CHECK(is_override=false OR stage='review')`、`CHECK(ends_at > starts_at)`。
- `notices`：`unique_notice_read_per_user`；`competitions`：`unique_competition_group_registration`；`equipment`：`equipment_available_lte_total` 与 `borrow_status_matches_return_date`；`discussion`：`discussion_board_name_ci_uniq`（板块英文名大小写不敏感唯一）。
- `core`：**不是约束但同级**——`core_auditlog` 上的行级触发器 `core_auditlog_append_only`（迁移 `0003`）拒掉 `UPDATE` / `DELETE`，是「审计只追加」的执行点。改名要动迁移，绕过（`DISABLE TRIGGER` 等）见 [deploy.md](../deploy.md) §5.3。

**这些约束名本身就是承诺**：改名要连迁移一起动，改行为（放宽/收紧）更要先想清存量数据怎么办。

完整的约束清单与「为什么」在各 app 的 `README.md`。

### C.3 迁移与旧数据

- **破坏性迁移纪律**：删字段／删表／改类型**不与依赖旧字段的功能同一次发布**——先加新列 + 双写，下次发布再删旧列。保证任意一版代码与当版数据库兼容，回滚才安全（[deploy.md](../deploy.md) §3）。
- **回填型迁移的取向**：认不出历史数据的字段**留空而不否决**（如获奖的 `tier` 为空不参与判重、老轮次的 `review_type` 为空回退 2 人）；缺文件只记 `private_media.missing` 警告并跳过，不中断整条迁移。
- **可重跑的迁移**：搬文件那条（`core.0002_rehome_protected_uploads`）幂等——两个根的相对路径相同，重跑只会发现目标已存在；反向迁移把文件搬回去。
- **删过模型之后**：跑一次 `manage.py remove_stale_contenttypes --noinput` 清掉指向已删模型的 `auth_permission`（[deploy.md](../deploy.md) §3）。
