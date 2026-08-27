# 阶段五验收标准：设备管理与借用登记

> 只有所有必选项通过，阶段五才算完成。

## 1. 验收范围

- 设备台账
- 设备启用/停用状态
- 成员直接借用登记（无审批）
- 成员查看自己的借用记录
- 成员归还自己的设备
- 管理员查看全部记录并代归还
- 库存扣减、回补和并发事务保护
- 管理后台维护与操作日志

## 2. 设备台账标准

| 编号 | 标准 | 验证方式 |
|---|---|---|
| E-01 | `Equipment` 有名称、分类、总量、可借数量、说明、启用状态和时间字段 | 模型/迁移 |
| E-02 | `available_count` 不得大于 `total_count` | 模型校验 + 数据库约束 + 自动测试 |
| E-03 | 有借用记录时，总量不得低于可借数量与已借出数量之和 | 模型/Admin 校验 + 自动测试 |
| E-04 | 仅启用设备展示在成员设备列表中 | 自动测试 |
| E-05 | 停用设备不能通过猜测 URL 进入借用页 | 自动测试 |
| E-06 | 管理员可维护设备；普通成员不能进入设备 Admin | 自动测试 |

## 3. 借用标准

| 编号 | 标准 | 验证方式 |
|---|---|---|
| B-01 | 登录成员可查看设备列表并登记借用 | 自动测试 |
| B-02 | 匿名访客不能查看或借用设备 | 自动测试 |
| B-03 | 借用必须填写不早于当天的计划归还日期 | 自动测试 |
| B-04 | 设备无可借数量时不能创建借用记录 | 自动测试 |
| B-05 | 借用成功创建 `EquipmentBorrow`，状态为 `borrowed` | 自动测试 |
| B-06 | 借用成功在同一事务中扣减设备可借数量 | 服务代码/自动测试 |
| B-07 | 借用记录包含设备、借用人、借用/计划归还日期、状态、备注、时间 | 模型/自动测试 |
| B-08 | 后台禁止手工新增借用记录，避免绕过库存事务 | Admin 配置检查 |

## 4. 归还与可见性标准

| 编号 | 标准 | 验证方式 |
|---|---|---|
| R-01 | 普通成员只可查看自己的借用记录 | 自动测试 |
| R-02 | 管理员可查看全部借用记录 | 自动测试 |
| R-03 | 普通成员只能归还自己的记录 | 自动测试 |
| R-04 | 管理员可以代成员归还 | 自动测试 |
| R-05 | 归还成功后状态为 `returned` 并填写实际归还日期 | 自动测试 |
| R-06 | 归还在同一事务中回补一个可借数量 | 服务代码/自动测试 |
| R-07 | 第二次归还不会再次回补库存 | 自动测试 |
| R-08 | 已归还状态必须有实际归还日期；实际归还日期不得早于借用日期 | 模型校验 + 自动测试 |
| R-09 | 后台归还使用专用事务操作；借用记录不允许删除 | Admin 配置检查 |

## 5. 日志标准

设备模块必须记录：

```text
equipment.list.view
equipment.borrow_list.view
equipment.borrow.success
equipment.borrow.failure
equipment.return.success
equipment.return.failure
equipment.return.denied
admin.equipment.save
```

日志应包括请求 ID、操作者、设备/借用记录 ID、库存变化或失败原因，且不记录密码。

## 6. 自动验收命令

```bash
.venv/bin/python -m compileall -q config accounts notices content media projects competitions equipment manage.py
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py migrate
.venv/bin/python manage.py test equipment --verbosity 2
.venv/bin/python manage.py test --verbosity 1
```

预期结果：

```text
System check identified no issues
No changes detected
阶段五测试全部 OK
全量测试全部 OK
```

## 7. 人工冒烟验收

1. 管理员进入 `/admin/`，创建一个启用设备，填写总量和可借数量。
2. 使用普通成员登录，访问 `/member/equipment/`，确认能看到设备和可借数量。
3. 借用设备，填写计划归还日期和备注，确认可借数量减一。
4. 再用另一成员借用，确认库存继续减少；库存为零后尝试再次借用，确认被拒绝。
5. 使用第一位成员打开 `/member/borrows/`，确认仅看到自己的记录。
6. 第一位成员归还设备，确认状态变为“已归还”、实际归还日期出现、库存加一。
7. 重复提交归还，确认库存不再增加。
8. 使用第二位成员尝试归还第一位成员的记录，确认返回 404。
9. 使用管理员打开 `/member/borrows/`，确认可以查看全部记录并代归还。
10. 停用设备后，确认成员设备列表不显示它，直接访问借用 URL 返回 404。
11. 查看 `logs/django.log`，确认借用/归还日志存在且无密码。

## 8. 完成门槛

以下任一项不满足，阶段五保持“未完成”：

- 任意测试失败
- 存在未生成迁移
- Django `check` 报错
- 库存可以借成负数或超出总量
- 无库存时仍能创建借用记录
- 成员能查看或归还他人的借用记录
- 重复归还重复回补库存
- 停用设备仍可借用
- 通过 Admin 手工新增/删除借用记录破坏库存
