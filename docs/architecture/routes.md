# 10. 页面与路由

> 全部页面与地址，按界面分组。

**什么时候看**：找一个地址对应哪个视图，或新增页面时挑位置。

---

### 10.1 公开门户（无需登录）

下表路径均为**中文**地址；每个地址前加 `/en/` 即为对应的英文页面（如 `/en/about/`），
地址即语言，与浏览器语言无关。切换入口在顶栏右端。

| 路径 | 页面 |
|---|---|
| `/` | 首页：社团影像切换区（HomeSlide，同屏单帧切换）+ 最新公开公告 + 公开内容入口 |
| `/about/` | 社团简介快捷地址（读取 ContentPage slug=about；未发布时显示空状态，不返回 404） |
| `/pages/` | 更多页面：已发布的通用 ContentPage 清单（不含 slug=about，首页「了解社团」入口） |
| `/pages/<slug>/` | 通用公开内容页（仅已发布的 ContentPage 可访问，未发布 404） |
| `/awards/` | 历年获奖列表 |
| `/showcase/` | 成员风采 |
| `/notices/` | 公开公告列表（一次列全，不分页——社团规模够用；页面上标了总条数） |
| `/notices/<id>/` | 公告详情 |
| `/login/` `/logout/` | 登录 / 登出 |

### 10.2 成员界面（需登录）

| 路径 | 页面 | 权限 |
|---|---|---|
| `/member/` | 成员首页：身份／评审与初审资格 + 社团概览（仅管理员与联系人可见）+ 操作面板（注册表渲染） | 登录 |
| `/member/notices/` | 内部通知 + 仅联系人可见通知列表/详情 | 登录（按受众过滤） |
| `/member/profile/` | 个人信息：左栏资料表单 + 右栏头像与「当前身份」（只读）+ 下方个人图册 | 本人 |
| `/member/profile/<id>/` | 其他成员的只读资料：头像、姓名、院系、身份、图册及明确公开的联系方式（不显示学号/邮箱） | 登录成员 |
| `/member/space/`、`/member/space/boards/<id>/` | 社团空间与板块帖子流（置顶优先、其余按时间倒序） | 登录成员 |
| `/member/space/boards/<id>/posts/new/`、`/member/space/posts/<id>/edit/` | 发帖、编辑本人帖子 | 登录成员 / 作者 |
| `/member/space/posts/<id>/comments/`、`/member/space/posts/<id>/delete/` | 评论、删除帖子；删帖级联删除评论 | 登录成员；删自己的帖或管理员删任意帖 |
| `/member/space/comments/<id>/delete/` | 删除一条评论（软删除，页面不再显示） | 评论作者或管理员 |
| `/member/space/images/<id>/` | 帖子图片本身（随机文件名落盘，经此路由按成员身份校验后才发出） | 登录成员 |
| `/member/space/posts/<id>/pin/` | 置顶/取消置顶 | 管理员 |
| `/member/space/boards/create/`、`/member/space/boards/<id>/delete/` | 前端创建板块或删除空板块 | Django 超级管理员 |
| `/member/profile/avatar/` | 上传／更换头像（POST，一张图盖掉旧的，旧文件随之删除） | 本人 |
| `/member/profile/avatar/delete/` | 删除头像，连同磁盘上的文件（POST） | 本人 |
| `/member/profile/gallery/` | 往个人图册加一张图（POST；单张 ≤5 MB、合计 ≤100 MB） | 本人 |
| `/member/profile/gallery/<id>/move/` | 上移／下移一位（POST，`direction=up|down`） | 本人（他人的图一律 404） |
| `/member/profile/gallery/<id>/layout/` | 改一张图的排布（POST，`layout=normal|wide|full`） | 同上 |
| `/member/profile/gallery/<id>/delete/` | 从图册删除一张图，连同文件（POST） | 同上 |
| `/member/password/` | 修改密码 | 本人 |
| `/member/projects/` | 项目组列表：无组员看全部可申请，组员看自己的组，联系人看全部；页首有「申请创建项目组」入口 | 登录 |
| `/member/projects/create/` | 申请创建项目组（名称与描述必填，申请人即项目组联系人） | 登录 |
| `/member/projects/create/requests/<req>/<action>/` | 同意/拒绝创建项目组申请（POST，按钮在「评审」页）；任一管理员同意即通过，处理完跳回「评审」页 | 管理员 |
| `/member/projects/<id>/apply/` | 申请加入项目组 | 登录且非该组成员 |
| `/member/projects/<id>/manage/` | 管理组：审核申请、移除成员、转让联系人、改组介绍与学院/指导老师 | 该组联系人/管理员 |
| `/member/projects/<id>/manage/requests/<req>/<action>/` | 通过/拒绝入组申请 | 该组联系人/管理员 |
| `/member/projects/<id>/manage/members/<user>/remove/` | 移除组员 | 该组联系人/管理员 |
| `/member/projects/<id>/manage/proposal/` | 上传 / 更新项目书（doc/docx/pdf） | 该组联系人/管理员 |
| `/member/projects/<id>/manage/submit/` | 提交项目书审核（选送审类型 + 可选提交说明） | 该组联系人/管理员 |
| `/member/projects/<id>/` | 项目组详情：学院与指导老师、成员、项目书、批注版项目书归档、初审与评审状态及历史 | staff / 该组成员 / 本轮初审人 / 被分配评审人 |
| `/member/projects/<id>/proposal/` | 下载当前项目书 | 同上 |
| `/member/reviews/` | 我的评审队列（初审与评审各三档：待办 / 已完成 / 已释放；超级评审另有「全部进行中」；管理员另有「创建项目组申请」） | 初审人 / 评审人 / 超级评审 / 管理员 |
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
- **「身份管理」分组**（`config/admin.py` 把六张名册从各自的 app 分组里提出来置顶）：

  | 名册 | 行里看得到 |
  |---|---|
  | 管理员 / 评审人 / 初审人 / 超级评审 | 该人的**全部身份**，以及手上有几件待办（评审人、初审人两列） |
  | 项目组联系人 | 他负责的项目组 |
  | 项目组成员 | 他所在的每个项目组，以及在各组里是联系人还是成员 |

  六张名册都是只读的（`core.admin.RoleRosterAdmin`），顶上有一句「这个身份从哪来」。
- **用户组（`auth.Group`）的成员直接在组页增删**：这个「组」只用于内部通知的投递范围（`Notice.visible_groups`），既不是项目组（`ProjectGroup`），也不是身份名册。组页的「组内用户」是一个穿梭框，左侧候选池是**全部账号**（一次挑一批人加进来），右侧是组内现成的人；候选与已选都渲染成「账号（姓名，学院）」。保存走 `accounts.services.set_group_members`：**整份覆盖**、与现状比对后只动真正变了的人（重复保存同一份名单既不写库也不留审计行，与 `set_qualification` 同一条口径），写入在事务里先 `select_for_update` 锁住该组那一行（两个管理员同时保存同一份名单，不会各读各的现状、拼出一份谁也没提交过的结果），每次真正的变更留一条 `accounts.group.membership.update` 审计（谁进来、谁出去）。
- 账号后台的「权限」区仍然可以逐个发放三种资格：`is_reviewer`（评审）、`is_preliminary_reviewer`（初审）、`is_super_reviewer`（超级评审）；三者在列表页可直接筛选。**批量**发放走用户列表页的六个动作（授予／撤销 × 三种资格），写入经 `accounts.services.set_qualification` 并留审计；新建账号的表单上也能直接勾选，省掉「先建号、再进详情页勾一遍」。
- 评审相关记录以**只读留痕**为主，四处例外：评审人请假的两个时间可在列表上直接改（`list_editable`）；待评审且该轮未判结论的评审任务可在详情页改派评审人；待初审且该轮仍在初审中的初审任务同理；**整轮送审可删除**（连同它的初审与评审任务，已归档的轮次除外）。写操作都经服务层或审计日志留痕。
- 按需定制更友好的发布表单（本期以 Admin 为主）。

---
