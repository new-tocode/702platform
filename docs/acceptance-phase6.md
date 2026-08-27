# 阶段六验收标准：操作入口、后台体验与审计

> 只有所有必选项通过，阶段六才算完成。

## 1. 验收范围

- `core` 应用
- 成员操作入口注册表
- 各业务 app 通过 `AppConfig.ready()` 注册入口
- 成员中心由注册表动态生成入口卡片
- 顶部成员导航由同一注册表动态生成
- 按登录状态、强制改密状态、Django 权限和自定义业务条件过滤入口
- Django Admin 站点标题定制
- 数据库审计日志
- 审计日志只读 Admin
- 账号、通知、内容、媒体、项目组、竞赛、设备等关键写操作审计
- 阶段一至五全量回归

## 2. 操作入口注册表标准

| 编号 | 标准 | 验证方式 |
|---|---|---|
| O-01 | `OperationEntry` 有稳定 key、显示名称、说明、URL、排序和可见性条件 | 模型/单元测试 |
| O-02 | 各业务 app 在 `AppConfig.ready()` 中注册入口 | 注册表测试 |
| O-03 | 重复 key 注册是幂等的，后注册定义替换前一条定义 | 自动测试 |
| O-04 | 入口按 `sort_order` 和 key 稳定排序 | 自动测试 |
| O-05 | 未登录用户没有成员操作入口 | 自动测试 |
| O-06 | `must_change_password=True` 的用户没有任何成员操作入口 | 自动测试 |
| O-07 | 自定义 `visible_when` 返回 False 时入口不显示 | 自动测试 |
| O-08 | 不存在的 URL 不会让成员页面 500，而是记录异常并跳过 | 代码检查/测试 |
| O-09 | 成员中心不再硬编码业务入口，而是遍历注册表 | 模板检查/人工冒烟 |
| O-10 | 顶部导航与成员中心使用同一组权限过滤后的入口 | 模板检查/人工冒烟 |
| O-11 | 新增入口只需在业务 app 注册，不修改成员中心主体模板 | 代码检查 |

当前预期注册入口：

```text
accounts.profile
accounts.password
notices.internal
projects.groups
competitions.registration
equipment.borrow
equipment.records
core.audit（仅拥有 core.view_auditlog 且为 staff 的管理员）
```

## 3. 审计日志标准

| 编号 | 标准 | 验证方式 |
|---|---|---|
| A-01 | `AuditLog` 保存操作者、操作名、目标类型、目标 ID、结构化详情、请求 ID、IP 和时间 | 模型/自动测试 |
| A-02 | 操作者删除后审计记录保留，操作者字段变为空 | 模型关系检查 |
| A-03 | 审计详情使用 JSON 保存，不能写入密码等敏感值 | 代码检查/自动测试 |
| A-04 | `record_audit()` 可以处理有用户、匿名或系统操作 | 自动测试 |
| A-05 | 审计日志可在 `/admin/core/auditlog/` 查询 | 自动测试/人工冒烟 |
| A-06 | 审计日志 Admin 禁止新增、修改和删除 | 自动测试 |
| A-07 | 密码修改写入审计事件，不写入密码 | 自动测试 |
| A-08 | 资料修改写入审计事件，只记录变更字段名称 | 自动测试 |
| A-09 | Admin 创建/修改用户、通知、内容、媒体、项目组、竞赛、设备写入审计 | 代码检查/代表性测试 |
| A-10 | 竞赛报名、设备借用和归还写入审计 | 自动测试/代码检查 |

## 4. 后台体验标准

| 编号 | 标准 | 验证方式 |
|---|---|---|
| U-01 | Admin 显示“竞赛社团平台管理后台”站点标题 | Admin 页面检查 |
| U-02 | Admin 显示“平台管理”首页标题 | Admin 页面检查 |
| U-03 | 审计日志列表支持按操作、目标类型、时间筛选 | Admin 配置检查 |
| U-04 | 审计日志支持按操作者、目标、请求 ID 搜索 | Admin 配置检查 |
| U-05 | 关键模型 Admin 有中文字段分组、筛选、搜索和只读时间/操作者字段 | Admin 配置检查 |

## 5. 安全标准

- 模板隐藏入口只是用户体验措施，后端权限检查仍必须存在。
- 审计详情不得写入密码、Session、Cookie、完整 POST 数据或敏感正文。
- 审计日志只能追加，不能被管理员在 Admin 中删除或编辑。
- `record_audit()` 的调用方只传入非敏感结构化信息。
- 审计写入失败不能静默吞掉；错误应进入详细日志并让事务/请求按实际情况失败。

## 6. 自动验收命令

```bash
.venv/bin/python -m compileall -q config accounts notices content media projects competitions equipment core manage.py
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py migrate --check
.venv/bin/python manage.py test core --verbosity 2
.venv/bin/python manage.py test --verbosity 1
```

预期结果：

```text
System check identified no issues
No changes detected
所有阶段六测试 OK
全量测试 OK
```

## 7. 人工冒烟验收

1. 使用超级管理员进入 `/admin/`，确认站点标题和首页标题已定制。
2. 登录普通成员，进入 `/member/`，确认操作卡片由注册表生成。
3. 确认普通成员只能看到个人信息、修改密码、内部通知、项目组、设备等允许入口。
4. 登录项目组组长，确认“竞赛报名”入口出现；普通成员看不到。
5. 直接访问被隐藏的 URL，确认后端仍按原有权限返回拒绝，而不是依赖前端隐藏。
6. 完成登录、资料修改、设备借用、设备归还、竞赛报名或 Admin 发布操作。
7. 管理员进入 `/admin/core/auditlog/`，确认能看到对应审计记录、操作者、目标、请求 ID 和详情。
8. 尝试在审计日志 Admin 中新增、修改、删除，确认全部不允许。
9. 检查日志文件，确认有 `audit.record`，且无明文密码。

## 8. 完成门槛

以下任一项不满足，阶段六保持“未完成”：

- 任意测试失败
- 存在未生成迁移或未应用迁移
- Django `check` 报错
- 成员中心入口仍需手工同步多个模板
- 强制改密用户可以看到或使用成员操作入口
- 入口显示权限和后端权限不一致
- 审计日志可以被编辑或删除
- 审计日志缺少操作者、目标或请求信息
- 日志或审计详情泄露密码、Cookie 或完整请求数据
