# 6.8 core

> 平台核心：操作入口注册表、审计日志，以及跨应用的权限口径与上传校验。

**什么时候看**：加一个成员入口、写审计、改通用上传校验。

---

```
AuditLog（审计日志）
  - user           FK(User)  操作者（可空，用户删除后保留记录）
  - action         操作名
  - target_type    目标类型（app_label.model_name）
  - target_id      目标 ID
  - detail         JSON  结构化非敏感信息
  - request_id     关联请求 ID
  - ip_address     请求来源 IP
  - created_at     发生时间
```

- 审计记录只能追加：Admin 只读，不允许新增、修改、删除。
- 所有 `record_audit()` 调用方只传入非敏感结构化信息，不得记录密码、Cookie 或完整请求数据。
