# 6.2 notices

> 公告（三种可见范围：公开 / 内部按用户组 / 仅联系人）与成员侧的「我的消息」。

**什么时候看**：改通知的受众口径、加一种新的可见范围，或给「我的消息」接新来源。

---

```
Notice
  - title          标题
  - content        正文（富文本/Markdown 渲染）
  - scope          可见范围：public（公开）| internal（内部）| contacts（仅联系人可见）
  - is_pinned      是否置顶（可选）
  - visible_groups M2M(Group)  内部通知可查看的用户组（仅 internal 需要，至少一个）
  - published_by   FK(User)  发布人（仅管理员）
  - published_at   发布时间
  - updated_at
  - attachments    M2M(MediaFile, blank=True)  配图/视频

NoticeRead
  - user      FK(User)            谁读过
  - notice    FK(Notice, CASCADE) 哪条通知（通知删除则回执一并删除）
  - read_at   已读时间
  唯一约束 (user, notice)
```

- `scope=public`：首页与公开公告列表可见，访客无需登录；公开通知不配置用户组。
- `scope=internal`：仅登录且已完成首次改密、并且属于 `visible_groups` 任一用户组的成员可见；访客和其他用户组不可见。
- `scope=contacts`：仅登录且已是任一项目组联系人（由 `ProjectGroup.leader` 计算）的成员可见，无需配置用户组。
- 成员想确认自己在哪些组上，看个人信息页「当前身份」末条的「用户组」即可（`accounts.selectors.member_identities`），不必问管理员。
- 可见性判定收敛在 `notices/visibility.py` 的 `member_visible_notices(user)` 单点，列表与详情共用同一过滤条件，未授权详情返回 404。

## 我的消息

成员中心里的 `/member/notices/`（入口、标题、面包屑都叫「我的消息」；公开通知另有 `/notices/` 公告栏，两条线并存）。来源分两类：

**广播型通知**（`Notice`）

- 可见集合见上面三条 scope；列表实时查，未读 = 可见通知 − `NoticeRead` 回执（不物化副本）。
- 进入详情即写回执（幂等）；发布人删除通知后成员侧自然消失，回执随 `CASCADE` 清掉，不留孤儿。

**事件型消息**（`Message` 表，一行一个收件人）

- 八个 kind 与触发点：@ 提及（帖子／评论，见 [discussion](discussion.md)）、评审任务（待初审／待评审）与结果、入组申请与结果、建组申请与结果。
- 行里只存结构化引用（`post`／`comment`／`submission`／`join_request`／`create_request` 五个可空外键，字符串引用）与已读状态；标题、链接、说明由 `notices/selectors.py` 现取现算，来源删除即级联删行。
- 点击走 `message/<pk>/go/` 中转：先标已读、再 302 到目标页（帖子锚点、项目组详情、评审页…）——目标页不必认识这条消息。
- 任务类消息跟着任务生命周期走：交掉／被释放／被改派即撤（`clear_review_task_messages`），历史归评审页。

**页面与口径**

- 行形状 `MessageRow`（类型／标题／url／时间／来自／说明／是否已读）是页面与来源之间的接缝：`_TYPE_LABELS` 给类型列，`_CONTENT_BUILDERS` 按 kind 分发「标题／链接／来自／说明」四个字段。排序是置顶通知在最前、其余按发生时间倒序混排。
- `unread_message_count` 与「全部已读」（POST 到 `read-all/`）同时覆盖两类；已读是高频个人操作，不写审计。
- 成员中心的提醒由 `notices/panels.member_home_context` 装配（与 `reviews.panels` 同一模式）：未读 > 0 时顶部出现提醒条、入口卡片挂计数徽标；模板按稳定 key `notices.internal` 认这一条——注册表是通用的，只有消息带计数，这是页面自己的特例。
- 遇到不认识的行（比如降级部署留下的 kind）跳过并记日志，不让整页 500。
