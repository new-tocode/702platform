# 阶段四验收标准：项目组与竞赛报名

> 只有所有必选项通过，阶段四才算完成。

## 1. 验收范围

- 项目组创建、组长和成员维护
- 组长自动属于自己的项目组
- 登录成员查看项目组
- 管理员发布竞赛信息
- 组长为自己负责的项目组登记报名
- 管理员可以为任意项目组登记
- 报名成员只能来自所选项目组
- 同组同赛不能重复报名
- 关闭或截止的竞赛不能报名
- Admin 权限隔离
- 操作日志和回归测试

## 2. 项目组标准

| 编号 | 标准 | 验证方式 |
|---|---|---|
| P-01 | `ProjectGroup` 有名称、组长、成员、简介和时间字段 | 模型/迁移 |
| P-02 | 创建项目组后，组长自动在成员列表中 | 自动测试 |
| P-03 | Admin 保存项目组后，组长不会被多选成员字段移除 | 自动测试 |
| P-04 | 已登录成员可以查看项目组列表 | 自动测试/人工冒烟 |
| P-05 | 匿名访客不能查看项目组列表 | 自动测试 |
| P-06 | 普通成员不能进入项目组 Admin | 自动测试 |
| P-07 | 管理员可以创建和维护项目组 | 自动测试/人工冒烟 |

## 3. 竞赛标准

| 编号 | 标准 | 验证方式 |
|---|---|---|
| C-01 | `Competition` 有名称、说明、截止时间、人数说明、开放状态和发布人 | 模型/迁移 |
| C-02 | Admin 新建竞赛时自动记录发布人 | 自动测试 |
| C-03 | 组长可以查看竞赛列表 | 自动测试 |
| C-04 | 普通成员不能进入竞赛管理功能 | 自动测试 |
| C-05 | 管理员可以进入竞赛管理功能 | 自动测试 |
| C-06 | `is_open=False` 时不能报名 | 自动测试 |
| C-07 | 当前时间超过 `deadline` 后不能报名 | 自动测试 |

## 4. 报名权限与数据标准

| 编号 | 标准 | 验证方式 |
|---|---|---|
| R-01 | 组长只能选择和提交自己负责的项目组 | 自动测试 |
| R-02 | 管理员可以为任意项目组登记 | 自动测试 |
| R-03 | 报名成员只能选择所选项目组的成员 | 自动测试 |
| R-04 | 服务端再次校验项目组和成员归属，不能依赖前端筛选 | 代码检查/自动测试 |
| R-05 | 同一项目组对同一竞赛只能登记一次 | 唯一约束 + 自动测试 |
| R-06 | 报名登记记录登记人、项目组、竞赛、成员、备注和时间 | 模型/自动测试 |
| R-07 | 登记成功后立即生效，不需要审批 | 自动测试 |
| R-08 | 越权、无效成员和重复登记不会创建部分数据 | 自动测试/事务检查 |

## 5. 日志标准

竞赛模块必须记录：

- `project_group.list.view`
- `competition.list.view`
- `competition.permission.denied`
- `competition.registration.success`
- `competition.registration.failure`
- `competition.registration.rejected`
- `admin.project_group.save`
- `admin.competition.save`
- `admin.competition_registration.save`

日志应包含请求 ID、操作者、对象 ID、失败原因和必要的数量信息，不得记录密码。

## 6. 自动验收命令

```bash
# 语法和 Django 配置
.venv/bin/python -m compileall -q config accounts notices content media projects competitions manage.py
.venv/bin/python manage.py check

# 迁移检查和应用
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py migrate

# 阶段四测试
.venv/bin/python manage.py test projects competitions --verbosity 2

# 全量回归
.venv/bin/python manage.py test --verbosity 1
```

预期结果：

```text
System check identified no issues
No changes detected
阶段四测试全部 OK
全量测试全部 OK
```

## 7. 人工冒烟验收

1. 管理员进入 `/admin/`。
2. 创建至少两个成员和两个项目组，并为每组设置组长和成员。
3. 确认每个组长自动出现在对应项目组成员中。
4. 登录普通成员，访问 `/member/projects/`，确认项目组、组长和成员正确展示。
5. 管理员创建一条开放竞赛，设置截止时间和组队人数说明。
6. 使用组长登录 `/member/competitions/`，确认看到竞赛和报名入口。
7. 进入报名页，确认只能选择自己负责的项目组和该组成员。
8. 提交报名，确认登记成功。
9. 再次提交同一项目组报名，确认被拒绝。
10. 使用另一项目组组长尝试提交第一组 ID，确认后端拒绝。
11. 管理员可以为任意项目组登记报名。
12. 关闭竞赛或设置过去的截止时间，确认不能报名。
13. 使用普通成员访问 `/member/competitions/`，确认返回 403。
14. 查看 `logs/django.log`，确认关键操作有日志且无密码。

## 8. 完成门槛

以下任一项不满足，阶段四保持“未完成”：

- 任意测试失败
- 存在未生成迁移
- Django `check` 报错
- 组长能为其他项目组报名
- 报名可提交非本组成员
- 重复报名能创建第二条记录
- 关闭或过期竞赛仍可报名
- 普通成员能进入竞赛管理页面
- 竞赛发布人或报名登记人没有记录
