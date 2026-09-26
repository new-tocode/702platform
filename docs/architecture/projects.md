# 6.4 projects

> 项目组：联系人（由 `leader` 计算）、指导老师、入组申请、申请建组。

**什么时候看**：动项目组成员关系、指导老师槽位，或建组审批流程。

---

```
ProjectGroup
  - name           组名
  - leader         FK(User)  项目组联系人（一个，唯一真相源）
  - members        M2M(User) 组员（保存时自动确保项目组联系人也在成员列表中）
  - description    简介
  - college        学院
  - created_at
  - updated_at

ProjectAdvisor（指导老师）
  - group          FK(ProjectGroup)
  - name           指导老师姓名（纯文本——平台没有教师账号可关联）
  - sort_order     槽位 0 / 1 / 2
  - created_at / updated_at
  - 槽位唯一约束 (group, sort_order) 加 CHECK(sort_order < 3)，两条合起来即「每组至多 3 位」；
    上限只有一处写法：projects.models.MAX_ADVISORS_PER_GROUP

GroupJoinRequest（入组申请）
  - group          FK(ProjectGroup)
  - applicant      FK(User)
  - message        申请理由
  - status         pending（待审核）| approved（已通过）| rejected（已拒绝）
  - decided_by     FK(User, 可空)  处理人
  - decided_at     处理时间
  - created_at / updated_at
  - 部分唯一约束：(group, applicant) 仅当 status=pending —— 同组同一人同时只有一条待审申请，被拒后可重新申请

GroupCreateRequest（创建项目组申请）
  - name / description    项目组名称与描述（申请时必填）
  - college               学院（选填）
  - advisor_1 / _2 / _3   指导老师三位固定槽位（选填，与 MAX_ADVISORS_PER_GROUP 一一对应）
  - applicant             FK(User)  申请人——通过后即新组的项目组联系人
  - status                pending（待审核）| approved（已通过）| rejected（已拒绝）
  - decided_by / decided_at
  - created_group         OneToOne(ProjectGroup, 可空)  通过后建成的项目组
  - created_at / updated_at
  - 部分唯一约束：(applicant) 仅当 status=pending —— 同一申请人同时只有一条待审申请，被拒后可重新申请
```

- 联系人身份**由 `ProjectGroup.leader` 计算**，不新建任何用户组存储；判定统一收敛在 `projects/permissions.py`。
- 联系人可审核入组申请、移除非联系人成员、修改项目组介绍、维护学院与指导老师、把联系人转让给组内成员（原联系人保留为普通成员）。
- **申请创建项目组**：任何登录成员（不论身份）都能在项目组页发起，申请人为项目组联系人；学院与指导老师可以先不填。
  - **审核人是全体管理员**，任一管理员同意即视为通过。`approve_create_request` 在事务内锁行并复查状态，其余管理员随后提交同一申请只会收到「该申请已被处理」，不会建出第二个组。
  - 通过后按申请内容建立正式 `ProjectGroup`（指导老师从申请的三列槽位转成 `ProjectAdvisor` 行）并出现在项目组列表中；拒绝则申请人可修改后重交。
  - 创建申请**后台只读留痕**；**处理入口只在管理员的「评审」页**——管理员不需要评审资格，`reviews.permissions.can_open_queue` 为此把 `is_staff` 也放行，「谁算管理员」的口径仍取自 `projects.permissions.can_decide_group_create_requests` 这一处。
- 学院与指导老师在同一张表单上维护：指导老师固定三行输入框，空槽位表示没有这一位，保存时按槽位顺序补齐（`projects.services.update_group_info`），因此不会撞上槽位唯一约束。学院与指导老师在项目组详情页与项目组列表页都对外展示。
