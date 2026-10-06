# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 这是什么

竞赛社团管理平台：Django 单体应用 + 服务端渲染模板，数据库**固定 PostgreSQL**（SQLite 已移除）。含公开门户、成员系统与 Django Admin 后台，界面中英双语——**中文是源语言**（地址不带前缀），英文走 `/en/` 前缀，地址即语言，后台 `/admin/` 不在双语范围内。

## 常用命令

先 `source env.local.sh`（**必须**，不加载连不上数据库），命令一律走项目 venv：

```bash
source env.local.sh
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run   # 预期 No changes detected
.venv/bin/python manage.py test                               # 全量，用测试库，不动开发库
.venv/bin/python manage.py test reviews.tests.test_preliminary        # 单模块
.venv/bin/python manage.py test accounts.tests.XxxTests.test_y        # 单条
.venv/bin/python manage.py runserver 127.0.0.1:8021 --noreload
```

**做完的定义**：`check` + `makemigrations --check --dry-run` + `test` 三项全绿；迁移文件与模型代码一起提交。

## 先读文档，别从代码里重新发现约定

| 要改什么 | 先读 |
|---|---|
| 某个领域（账号／项目组／评审／通知／社团空间……） | `docs/architecture/<app>.md`——按 app 分篇，讲表结构、**为什么这么设计**、**改动时不能破坏什么** |
| 权限、整体结构 | `docs/architecture/permissions.md`、`overview.md`（绝大多数「这个功能谁能用」的答案在这里） |
| 环境、分层约定、FAQ | `docs/development.md` |
| 部署、回滚、备份 | `docs/deploy.md` |
| 要在真实页面上验证改动、截图、端到端走一遍 | `run-local` skill（本机 `.claude/skills/run-local/`，因含演示账号口令而不进版本库） |

## 分层约定

每个 app 的模块分工是固定的，视图与 admin 都不越层：

| 模块 | 职责 | 规矩 |
|---|---|---|
| `models.py` | 表结构与不变量 | 不查别的应用 |
| `permissions.py` | 「谁能做什么」的判定 | **判定只写这里**，视图、模板、`panels` 都来问它 |
| `services.py` | 写操作：事务边界、审计、领域异常 | 视图与 admin 都调它，不自己写事务 |
| `selectors.py` | 只读查询与派生状态 | 不写库 |
| `views.py` | 取对象 → 调服务 → 渲染 | 不写事务、不写审计 |
| `panels.py` | 页面上下文装配 | 判定与取数都委托出去 |

- 跨应用只经对方的 `permissions` / `services` / `selectors` 公开函数，不直接查对方的模型（模型外键除外）；要打断加载期依赖时用函数内局部 import 并写明理由。
- 视图权限门槛一律用 `core.permissions.require(request, predicate, event, **fields)`；「谁算管理员」问 `core.permissions.is_admin`，不写 `user.is_staff`。
- 写操作经 `core.audit.record_audit` 留痕，**action 字符串一旦发布就不再改**。
- `services.py` 只为「被多处复用」或「含多表事务 / 约束翻译」的写操作而建；只有一个调用点的「保存 + 一条审计」留在视图里更清楚。
- 用户可见文案归模板与 `panels`；服务层抛领域异常，由视图翻译成 `messages`。

## 容易踩的坑

- **上传件分两类**：公开配图落 `mediafiles/`（Nginx 直出）；项目书、批注版、头像、图册等受保护件落 `protected_media/`（刻意不在 `mediafiles/` 之下），落盘名换成 uuid，取件一律经视图做权限判定。新增上传模型先想清属于哪类；模板里**不要写 `{{ field.url }}`**（存储刻意让它抛异常），用 `{{ field|file_url }}`。
- **i18n**：前台文案一律 `gettext`；不拼接句子（用 `%(name)s` 占位）；惰性译文不要在模块／类体里插值（那会在导入时定型，用 `format_lazy`）；给成员用的 `ModelForm` 要在 `Meta.labels` 写一遍标签（模型的 `verbose_name` 不进 `.po`）。改完文案跑 `makemessages -l en --no-obsolete` 填 `.po`，兜底测试会抓漏译。
- **样式只在 `static/css/app.css`**：模板不写行内样式、不写内联 `<script>`，页面脚本放 `static/js/`。
- **`reviews` 是状态机**：状态变更一律经 `reviews/lifecycle.py` 的 `transition()`（唯一写入点），页面上下文走 `panels.py`，判定走 `permissions.py`。
- **测试快是配置出来的**：只在 `manage.py test` 时把 `PASSWORD_HASHERS` 换成 MD5（`config.settings.running_tests()`），别顺手改掉。
- **`/etc` 下的配置归 `install.sh` 管**：改了 `deploy/` 里的模板要「先 `deploy.sh` 再 `install.sh`」，并读回线上文件核对；`deploy.sh` 只检查、不修。

## 工作节奏

- 多阶段改造：先切分支 → 写可勾选的 `TASKS.md`（已被 gitignore，属过程文件，做完删掉）→ 每阶段一个提交，阶段内保持三项检查全绿。
- 提交信息写中文，讲清**为什么这么改**并附测试结果（与仓库既有风格一致）。
- **仓库是公开的**：代码、注释、提交信息、PR 标题与描述一律用占位符，不写真实部署信息（公网 IP、域名、实例 ID、部署用户名、正在运行的服务版本号）。
