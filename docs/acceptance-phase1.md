# 阶段一验收标准：项目骨架与账号体系

> 本文档是阶段一的可执行验收清单。只有所有必选项通过，阶段一才算完成。

## 1. 验收范围

阶段一只覆盖：

- Django 项目基础结构与本地虚拟环境
- 自定义 `AUTH_USER_MODEL`
- 管理员创建账号、管理员重置密码
- 成员登录、登出
- 首次登录强制修改管理员发放的初始密码
- 成员修改个人资料
- 成员后续修改密码
- 禁止公开注册
- 请求、认证、密码修改、资料修改、异常的详细日志

阶段一不覆盖公告、项目组、竞赛、设备和媒体上传，它们在后续阶段实现。

## 2. 功能验收标准

| 编号 | 标准 | 验证方式 |
|---|---|---|
| A-01 | `manage.py check` 无错误 | 自动命令 |
| A-02 | 数据库迁移可从空库完整执行 | 自动命令 |
| A-03 | `AUTH_USER_MODEL` 为 `accounts.User` | 自动测试/配置检查 |
| A-04 | 管理员创建的普通账号默认 `must_change_password=True` | 自动测试 + Admin 测试 |
| A-05 | `createsuperuser` 创建的超级管理员不被强制改密 | 自动测试 |
| A-06 | 普通账号可以登录，成功后直接进入改密页 | 自动测试 |
| A-07 | 初始密码未修改时，成员首页、资料页等成员功能均被拦截 | 自动测试 |
| A-08 | 初始改密成功后，标志置为 `False`，成员首页可访问 | 自动测试 |
| A-09 | 初始改密使用密码校验规则，错误提交不得解锁账号 | 自动测试 |
| A-10 | 改密后成员可以维护自己的个人资料 | 自动测试 |
| A-11 | 后续改密必须输入正确旧密码 | 自动测试 |
| A-12 | 管理员重置密码后，目标账号重新进入强制改密流程 | 自动测试 |
| A-13 | 不存在公开注册路由 | 自动测试 |
| A-14 | 非管理员不能进入 Django Admin | 自动测试 |
| A-15 | 外部 `next` URL 被拒绝，防止开放重定向 | 自动测试 |
| A-16 | 登录失败日志不记录明文密码 | 自动测试 |

## 3. 日志验收标准

日志文件：`logs/django.log`，开发时同时输出到终端。

每条请求日志必须包含：

- 请求 ID（`request_id`）
- HTTP 方法、路径、查询字符串
- 用户名/用户 ID 或 `anonymous`
- 来源 IP
- 响应状态码
- 请求耗时（毫秒）

认证流程必须记录：

- 登录成功/失败
- 是否需要强制改密
- 强制改密重定向
- 密码修改成功/失败
- 资料保存成功/失败
- 管理员创建或修改账号

安全要求：

- 不得记录任何明文密码
- 异常必须包含 traceback（`logger.exception`）
- 日志采用轮转文件，单文件默认 10 MB，保留 5 个备份

## 4. 一键验收命令

在项目根目录执行：

```bash
# 1. 安装依赖（首次执行）
.venv/bin/python -m pip install -r requirements.txt

# 2. 静态配置检查
.venv/bin/python manage.py check

# 3. 检查是否存在未提交的模型迁移
.venv/bin/python manage.py makemigrations --check --dry-run

# 4. 使用测试数据库执行阶段一全部测试
.venv/bin/python manage.py test accounts --verbosity 2

# 5. 查看最近日志（仅开发排查使用）
python3 -c "from pathlib import Path; p=Path('logs/django.log'); print(p.read_text(encoding='utf-8')[-8000:] if p.exists() else '日志文件尚未生成')"
```

预期结果：

- `check`：`System check identified no issues`
- `makemigrations --check --dry-run`：无迁移变更输出，退出码 0
- `test accounts`：所有测试 `OK`
- 日志中能找到 `request.start`、`request.end`、`auth.login.success` 或 `auth.login.failure` 等事件

## 5. 人工冒烟验收（可选但建议）

```bash
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver
```

浏览器检查：

1. `/` 匿名可访问。
2. `/admin/` 使用超级管理员进入。
3. Admin 创建一个普通成员账号并设置初始密码。
4. 使用普通账号登录，必须先跳转到 `/member/password/`。
5. 未改密前直接访问 `/member/`，仍会被拦截。
6. 修改密码后能访问成员中心和 `/member/profile/`。
7. Admin 重置该成员密码后，再次登录又必须改密。
8. 页面没有“注册”入口，直接访问 `/register/` 返回 404。

## 6. 完成门槛

以下任一项不满足，阶段一保持“未完成”：

- 任意自动化测试失败
- 存在未生成的模型迁移
- Django `check` 报错
- 强制改密可以被 URL 直接绕过
- 管理员重置密码后账号未重新强制改密
- 日志泄露密码或关键认证事件缺失
