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

成员中心里的 `/member/notices/`（入口、标题、面包屑都叫「我的消息」，公开通知那条线不动）：

- **没有消息副本表**：列表实时查可见通知，未读 = 可见通知 − `NoticeRead` 回执。`notices/selectors.py` 的 `message_rows`（装配行）与 `unread_message_count`（计数）是页面与提醒共用的唯一口径。
- **行形状 `MessageRow`**（类型／标题／url／时间／发布人／范围文本／是否已读）是页面与消息来源之间的接缝：接帖子 @ 提及、评审通知时只扩展 `message_rows` 的装配，列表页与模板不用动。类型现在只有「内部通知」一个值；范围文本对内部通知列用户组名（逗号分隔），对仅联系人通知写「仅项目组联系人」。
- **已读**：进入详情即写回执（`notices/services.mark_read`，幂等）；「全部已读」是 POST 到 `read-all/`，`mark_all_read` 只动当前可见的未读，`ignore_conflicts` 挡住并发重复。已读是高频个人操作，不写审计。
- **删除的连带**：发布人删除通知后，列表与计数都来自实时查询，成员侧自然消失；回执随 `CASCADE` 清掉，不留孤儿。
- **成员中心的提醒**由 `notices/panels.member_home_context` 装配（与 `reviews.panels` 同一模式）：未读 > 0 时顶部出现提醒条、入口卡片挂计数徽标；模板按稳定 key `notices.internal` 认这一条——注册表是通用的，只有消息带计数，这是页面自己的特例。
