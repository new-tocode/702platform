# 竞赛社团管理平台

Django 单体应用，采用服务端渲染，当前已实现账号、通知、公开展示和媒体库基础能力。

## 当前状态

- Django + Django REST Framework 基础骨架
- 自定义 `accounts.User` 和 `Profile`
- 管理员创建账号/重置密码
- 成员登录、登出、个人资料维护
- 首次登录强制修改初始密码
- 公开通知和内部通知（管理员发布、范围隔离、置顶排序、用户组可见性）
- 公开展示内容（社团简介、历年获奖、成员风采）
- 图片/视频媒体库（类型、大小、签名校验）
- 详细请求与认证日志：`logs/django.log`
- 阶段一验收标准：`docs/acceptance-phase1.md`
- 阶段二验收标准：`docs/acceptance-phase2.md`
- 阶段三验收标准：`docs/acceptance-phase3.md`
- 通知用户组验收标准：`docs/acceptance-notice-groups.md`
- 逐命令运行与配置说明：`docs/project-guide.md`
- 总体架构：`docs/architecture.md`

现有的 `社团评审系统_发布版.zip` 是单独保留的历史压缩包，不参与当前 Django 项目运行。

## 快速开始

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver
```

访问：

- 公开首页：<http://127.0.0.1:8000/>
- 成员登录：<http://127.0.0.1:8000/login/>
- 管理后台：<http://127.0.0.1:8000/admin/>

账号不开放公开注册。管理员在 Admin 中创建普通账号，成员首次登录必须修改初始密码。

## 阶段一验收

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py test accounts --verbosity 2
```

任何测试失败、存在未提交迁移或 Django 检查报错，都不能视为阶段一完成。

## 阶段二验收

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py migrate
.venv/bin/python manage.py test notices --verbosity 2
.venv/bin/python manage.py test --verbosity 1
```

阶段二详细标准见 `docs/acceptance-phase2.md`，覆盖公开/内部通知隔离、管理员发布、置顶排序、用户组可见性、首页展示和强制改密联动。

## 阶段三验收

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py migrate
.venv/bin/python manage.py test content media --verbosity 2
.venv/bin/python manage.py test --verbosity 1
```

阶段三详细标准见 `docs/acceptance-phase3.md`，覆盖公开栏目、未发布内容隔离、图片/视频上传校验、媒体关联、Markdown 安全渲染和管理员维护。

## 日志

开发环境日志同时输出到终端并写入 `logs/django.log`。每个请求带有 `X-Request-ID` 响应头和对应 `request_id` 日志字段，认证日志不会记录明文密码。

生产环境至少设置：

```bash
export DJANGO_SECRET_KEY='replace-with-a-long-random-secret'
export DJANGO_DEBUG='0'
export DJANGO_ALLOWED_HOSTS='your-domain.example'
export DJANGO_SESSION_COOKIE_SECURE='1'
export DJANGO_CSRF_COOKIE_SECURE='1'
```
