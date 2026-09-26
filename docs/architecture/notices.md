# 6.2 notices

> 公告：三种可见范围（公开 / 内部按用户组 / 仅联系人）。

**什么时候看**：改通知的受众口径，或加一种新的可见范围。

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
```

- `scope=public`：首页与公开公告列表可见，访客无需登录；公开通知不配置用户组。
- `scope=internal`：仅登录且已完成首次改密、并且属于 `visible_groups` 任一用户组的成员可见；访客和其他用户组不可见。
- `scope=contacts`：仅登录且已是任一项目组联系人（由 `ProjectGroup.leader` 计算）的成员可见，无需配置用户组。
- 可见性判定收敛在 `notices/visibility.py` 的 `member_visible_notices(user)` 单点，列表与详情共用同一过滤条件，未授权详情返回 404。
