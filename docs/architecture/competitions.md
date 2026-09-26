# 6.5 competitions

> 竞赛与报名：谁能为哪个组报名、参赛成员与竞赛组长的约束。

**什么时候看**：改报名规则、加竞赛字段。

---

```
Competition
  - title          竞赛名称
  - description    说明
  - deadline       报名截止时间
  - team_size      组队人数要求（如 min/max 或文本说明）
  - is_open        报名是否开放
  - published_by   FK(User)  发布人（仅管理员）
  - published_at
  - created_at
  - updated_at

CompetitionRegistration
  - competition    FK(Competition)
  - group          FK(ProjectGroup)
  - registered_by  FK(User)  登记人（审计用；应为该组项目组联系人或管理员）
  - team_leader    FK(User, 可空)  竞赛组长（为该竞赛指定的角色，从参赛成员中选，可与登记人不同）
  - members        M2M(User) 参赛成员（从组内选择）
  - remark         备注
  - created_at
  - updated_at
  - 唯一约束：(competition, group) —— 每组每赛只登记一次
```

- 管理员发布竞赛信息；项目组联系人只能为自己负责的项目组登记报名，管理员可以为任意项目组登记（对象级权限校验，见 [permissions.md](permissions.md)）。
- 报名成员只能从所选项目组成员中选择；竞赛组长必须从所选参赛成员中指定（可为联系人本人）。
- 同一项目组对同一竞赛只能登记一次，由 `(competition, group)` 唯一约束保证。
- 报名必须在 `is_open=True` 且未超过 `deadline` 时提交。
- 报名后，联系人可在竞赛页修改报名信息或放弃报名（截止前）。
- 无审批流：登记即生效。
