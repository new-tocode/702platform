# 项目运行与配置说明

本文档说明当前 Django 项目的目录、依赖、启动命令、测试命令、环境变量和管理员操作。命令默认在项目根目录 `/home/alen/work/702platform` 执行。

> 当前实现对应开发阶段 6：项目骨架、账号登录、管理员发放账号、强制首次改密、个人资料维护、公开/内部通知、公开展示内容、媒体库、项目组、竞赛报名、设备台账与借用登记，以及操作入口注册表、管理后台体验和数据库审计日志。成员中心与顶部导航由注册表动态生成入口，关键写操作写入 `AuditLog`，后台只读查看。站内消息可作为后续扩展。

---

## 1. 当前项目结构

```text
.
├── manage.py                         # Django 命令入口
├── requirements.txt                  # Python 依赖及版本范围
├── README.md                         # 简要入口说明
├── config/                           # Django 项目配置包
│   ├── settings.py                   # 全局配置和环境变量读取
│   ├── urls.py                       # 根路由
│   ├── admin.py                      # Admin 站点标题定制
│   ├── middleware.py                 # 请求日志、强制改密
│   ├── logging.py                    # 日志格式化器
│   ├── asgi.py                       # ASGI 部署入口
│   └── wsgi.py                       # WSGI 部署入口
├── accounts/                         # 账号与成员资料应用
│   ├── models.py                     # User、Profile
│   ├── forms.py                      # 登录后改密、个人资料、Admin 表单
│   ├── views.py                      # 首页、登录、成员中心、资料、改密
│   ├── urls.py                       # accounts 路由
│   ├── admin.py                      # Django Admin 配置
│   ├── signals.py                    # Profile 自动创建、认证日志
│   ├── migrations/                   # 数据库迁移文件
│   └── tests.py                      # 阶段一验收测试
├── notices/                          # 公开与内部通知应用
│   ├── models.py                     # Notice 和可见范围
│   ├── views.py                      # 公开/内部列表与详情
│   ├── urls.py                       # 公开通知路由
│   ├── member_urls.py                # 内部通知路由
│   ├── admin.py                      # 管理员发布配置
│   ├── migrations/                   # 通知数据库迁移
│   └── tests.py                      # 阶段二验收测试
├── content/                          # 公开展示内容应用
│   ├── models.py                     # ContentPage、Award、Showcase
│   ├── views.py                      # 简介、获奖、成员风采页面
│   ├── urls.py                       # 公开展示路由
│   ├── admin.py                      # 管理员内容维护
│   ├── templatetags/rendering.py     # Markdown 安全渲染
│   └── tests.py                      # 阶段三展示测试
├── media/                            # 图片/视频媒体库应用
│   ├── models.py                     # MediaFile
│   ├── validators.py                 # 类型、大小、签名校验
│   ├── admin.py                      # 管理员上传配置
│   └── tests.py                      # 媒体验证测试
├── equipment/                        # 设备台账和借用应用
│   ├── models.py                     # Equipment、EquipmentBorrow
│   ├── services.py                   # 事务化借用/归还和库存更新
│   ├── forms.py                      # 借用和设备 Admin 表单
│   ├── views.py                      # 设备、借用记录、归还页面
│   ├── admin.py                      # 后台设备维护和代归还
│   └── tests.py                      # 阶段五验收测试
├── core/                             # 平台核心应用
│   ├── registry.py                   # 操作入口注册表
│   ├── models.py                     # AuditLog 审计日志
│   ├── audit.py                      # 统一审计记录函数
│   ├── context_processors.py         # 向模板注入成员操作入口
│   ├── admin.py                      # 只读审计后台
│   ├── apps.py                       # AppConfig、审计入口注册
│   ├── migrations/                   # 数据库迁移
│   └── tests.py                      # 阶段六验收测试
├── templates/                        # 服务端渲染模板
├── static/                           # 开发静态文件目录
├── mediafiles/                       # 上传媒体存储目录（MEDIA_ROOT）
├── logs/                             # 日志目录
├── docs/
│   ├── architecture.md               # 总体架构设计
│   ├── acceptance-phase1.md          # 阶段一验收标准
│   ├── acceptance-phase2.md          # 阶段二验收标准
│   ├── acceptance-phase3.md          # 阶段三验收标准
│   ├── acceptance-phase4.md          # 阶段四验收标准
│   ├── acceptance-phase5.md          # 阶段五验收标准
│   ├── acceptance-phase6.md          # 阶段六验收标准
│   ├── deploy.md                     # 快速测试部署说明
│   ├── deploy-production.md          # 生产部署与更新手册
│   └── project-guide.md             # 本说明文档
├── deploy/                           # 生产部署工件
│   ├── deploy.sh                     # 发布脚本（备份→切版本→测试→迁移→重启）
│   ├── backup.sh                     # 每日备份脚本（cron 调用）
│   ├── club702.service               # systemd unit 模板
│   └── nginx-club702.conf            # Nginx 站点模板
└── db.sqlite3                        # 本地开发数据库，首次 migrate 后生成
```

`.venv/`、`__pycache__/`、`db.sqlite3`、日志文件和运行时上传文件属于本机生成内容，不应提交到版本库。规则见 `.gitignore`。

项目根目录中的 `社团评审系统_发布版.zip` 是单独保留的历史压缩包，不参与当前 Django 项目的运行。

---

## 2. 依赖说明

`requirements.txt` 中每一行是一个依赖：

| 依赖 | 作用 |
|---|---|
| `Django>=5.2,<5.3` | Web 框架、ORM、认证、Session、Admin、迁移、模板和测试框架。限定在 Django 5.2 系列。 |
| `djangorestframework>=3.16,<3.17` | 为后续小程序、App 或外部系统接口预留，本阶段尚未作为主要页面渲染方式。 |
| `bleach>=6.2,<7` | 后续富文本内容的 HTML 白名单过滤，降低 XSS 风险。 |
| `markdown>=3.8,<4` | 后续 Markdown 内容渲染。 |
| `Pillow>=11.3,<12` | 校验上传图片的真实格式和文件完整性。 |

版本写成“下限 + 上限”是为了允许补丁版本更新，同时避免未经验证的主版本变化。例如 `Django>=5.2,<5.3` 会安装 5.2.x，但不会自动升级到 5.3。

---

## 3. 第一次安装

### 3.1 进入项目目录

```bash
cd /home/alen/work/702platform
```

- `cd`：切换当前 Shell 的工作目录。
- 后续相对路径（例如 `logs/django.log`、`db.sqlite3`）都以当前目录为基准。

### 3.2 检查 Python

```bash
python3 --version
python3 -m pip --version
```

- `python3 --version`：确认 Python 版本。当前项目已在 Python 3.13.11 上验证。
- `python3 -m pip --version`：确认 pip 属于当前 Python。使用 `python3 -m pip` 比直接调用 `pip` 更不容易误用另一套 Python 环境。

### 3.3 创建虚拟环境

```bash
python3 -m venv .venv
```

- `python3 -m venv`：使用 Python 内置模块创建隔离环境。
- `.venv`：环境目录名称；项目命令通过 `.venv/bin/python` 明确使用这个环境。
- 如果 `.venv` 已经存在，不需要重复创建；可以直接执行下一步。

### 3.4 更新 pip 并安装项目依赖

```bash
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

- `.venv/bin/python`：调用虚拟环境里的 Python。
- `-m pip`：让该 Python 运行它自己的 pip。
- `install --upgrade pip`：更新虚拟环境中的 pip，不修改系统 pip。
- `install -r requirements.txt`：读取依赖文件并安装所有依赖。
- `-r` 是 `--requirement` 的缩写。

Windows 或已激活虚拟环境的 Shell 可以把路径写成对应形式；本项目当前按 Linux/WSL 的 `.venv/bin/python` 命令记录。

### 3.5 初始化数据库

```bash
.venv/bin/python manage.py migrate
```

- `manage.py` 是 Django 管理命令入口。
- `migrate`：按照迁移文件创建或更新数据库表。
- 第一次执行会创建 `db.sqlite3`，并建立 Django Admin、认证、Session 和 `accounts` 表。
- 该命令可以重复执行；已经应用的迁移不会重复执行。
- 不要用手工建表代替迁移，否则模型和数据库状态可能不一致。

### 3.6 创建第一个超级管理员

```bash
.venv/bin/python manage.py createsuperuser
```

命令会交互式询问用户名、邮箱和密码。

- 该账号用于进入 `/admin/`。
- 通过 `createsuperuser` 创建的超级管理员会自动设置 `must_change_password=False`，不会被普通成员的强制改密中间件拦截。
- 密码必须使用不容易猜测的值；不要把实际密码写进文档、脚本或版本库。

### 3.7 启动开发服务器

```bash
.venv/bin/python manage.py runserver
```

- `runserver`：启动 Django 开发服务器。
- 默认监听 `127.0.0.1:8000`。
- 代码文件变化时默认自动重载。
- 只适合本地开发和冒烟测试，不是生产部署服务器。

指定监听地址和端口：

```bash
.venv/bin/python manage.py runserver 0.0.0.0:8000
```

- `0.0.0.0`：监听所有网卡，允许其他机器访问；仅在明确需要时使用。
- `8000`：端口号，可替换为其他未占用端口。

关闭自动重载，适合脚本化冒烟测试：

```bash
.venv/bin/python manage.py runserver 127.0.0.1:8765 --noreload
```

- `127.0.0.1:8765`：只在本机监听 8765 端口。
- `--noreload`：关闭开发服务器的自动重载，避免测试脚本启动两个进程。

访问地址：

- 首页：<http://127.0.0.1:8000/>
- 成员登录：<http://127.0.0.1:8000/login/>
- 管理后台：<http://127.0.0.1:8000/admin/>

---

## 4. 第一次管理员操作

1. 打开 `/admin/`，使用 `createsuperuser` 创建的账号登录。
2. 在“用户”中新增普通成员账号。
3. 设置用户名、姓名、邮箱和初始密码。
4. 将账号信息安全地发给成员。
5. 成员访问 `/login/` 登录。
6. 成员首次登录会自动跳转到 `/member/password/`。
7. 修改成功后才可以访问成员中心和个人资料页。
8. 如果成员忘记密码，管理员打开该用户的修改页面，使用“重置密码”入口设置新密码。重置后该成员下次登录仍然必须改密。

当前没有注册 URL，也没有自助找回密码流程。直接访问 `/register/` 应返回 404；忘记密码由管理员处理。

---

## 5. Django 管理命令详解

### 5.1 配置检查

```bash
.venv/bin/python manage.py check
```

检查 URL、模型、Admin、模板配置和 Django 系统设置中的错误。该命令不修改数据库。

部署检查：

```bash
.venv/bin/python manage.py check --deploy
```

`--deploy` 会额外检查生产安全设置。开发环境默认 `DEBUG=True`、未启用 HTTPS Cookie 和 HSTS 时出现警告是预期现象；生产环境应按照第 7 节配置后重新执行。

### 5.2 迁移检查

查看是否有模型变更却没有迁移文件：

```bash
.venv/bin/python manage.py makemigrations --check --dry-run
```

- `makemigrations`：根据模型生成迁移文件。
- `--check`：发现需要迁移时以失败状态退出。
- `--dry-run`：只检查，不写入迁移文件。
- 验收时预期输出 `No changes detected`，退出码为 0。

模型变更后生成迁移：

```bash
.venv/bin/python manage.py makemigrations
```

该命令会在对应 app 的 `migrations/` 中生成文件。迁移文件必须和模型代码一起提交。

只为指定应用生成迁移：

```bash
.venv/bin/python manage.py makemigrations accounts
```

应用迁移：

```bash
.venv/bin/python manage.py migrate
```

查看迁移状态：

```bash
.venv/bin/python manage.py showmigrations
```

方括号中的 `[X]` 表示已应用，`[ ]` 表示未应用。

### 5.3 测试

运行 accounts 阶段一测试：

```bash
.venv/bin/python manage.py test accounts --verbosity 2
```

- `test accounts`：只运行 `accounts` 应用的测试。
- `--verbosity 2`：输出测试发现、迁移和每个测试名称，适合验收排查。
- 测试使用临时测试数据库，默认不会污染开发用的 `db.sqlite3`。

运行整个项目测试：

```bash
.venv/bin/python manage.py test --verbosity 1
```

- 不指定 app 时发现并运行项目中的所有测试。
- `--verbosity 1` 输出适中，适合日常运行。
- `--verbosity 0` 减少输出，仅适合快速确认成功/失败。

运行单个测试类或测试方法：

```bash
.venv/bin/python manage.py test accounts.tests.MemberAuthenticationAcceptanceTests
.venv/bin/python manage.py test accounts.tests.MemberAuthenticationAcceptanceTests.test_first_password_change_unlocks_member_area_and_updates_flag
```

### 5.4 Python 语法检查

```bash
.venv/bin/python -m compileall -q config accounts manage.py
```

- `compileall`：编译 Python 文件，检查语法错误。
- `-q`：只输出错误，不输出每个成功编译的文件。
- `config accounts manage.py`：只检查当前项目代码，不扫描 `.venv`。

### 5.5 静态文件收集

当前阶段没有完整的生产静态文件流程，后续部署前可使用：

```bash
.venv/bin/python manage.py collectstatic --noinput
```

- 将各应用的静态资源复制到 `STATIC_ROOT`，当前为 `staticfiles/`。
- `--noinput`：遇到确认提示时采用默认行为，适合自动化脚本。
- 生产环境应由 Nginx 或其他静态文件服务器提供 `staticfiles/`，不要让 Django 开发服务器承担该职责。

---

## 6. 验收命令

阶段一的完整验收流程：

```bash
# 安装依赖
.venv/bin/python -m pip install -r requirements.txt

# 检查 Django 配置
.venv/bin/python manage.py check

# 检查是否遗漏迁移
.venv/bin/python manage.py makemigrations --check --dry-run

# 执行完整测试
.venv/bin/python manage.py test --verbosity 1
```

每一条命令都必须成功。阶段一的详细标准见 [`acceptance-phase1.md`](acceptance-phase1.md)。

人工冒烟测试：

```bash
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver
```

检查首页、登录、Admin、创建成员、强制改密、资料修改和管理员重置密码流程。

使用 `curl` 检查本机 HTTP 响应：

```bash
curl -i http://127.0.0.1:8000/
curl -i http://127.0.0.1:8000/login/
curl -I http://127.0.0.1:8000/
```

- `curl`：命令行 HTTP 客户端。
- `-i`：同时显示响应头和响应体。
- `-I`：只发送 HEAD 请求并显示响应头。
- 响应应包含 `X-Request-ID`，用于从 `logs/django.log` 关联同一次请求。

---

## 7. 配置项详解

配置文件是 `config/settings.py`。支持的环境变量如下。环境变量优先于代码中的默认值。

| 环境变量 | 默认值 | 作用 | 生产建议 |
|---|---|---|---|
| `DJANGO_SECRET_KEY` | 开发专用固定字符串 | Django 签名、Session 和安全令牌使用的密钥 | **必须设置**为随机长字符串，不得提交到版本库 |
| `DJANGO_DEBUG` | `1` / `True` | 是否启用调试模式 | 生产设置为 `0` |
| `DJANGO_ALLOWED_HOSTS` | 空列表 | 允许访问的 Host，多个值用逗号分隔 | 设置为域名和必要的 IP，如 `example.com,www.example.com` |
| `DJANGO_DB_ENGINE` | `django.db.backends.sqlite3` | 数据库后端 | 本地保持默认；换 PostgreSQL 时需要同时安装驱动并补充连接配置 |
| `DJANGO_DB_NAME` | 项目根目录 `db.sqlite3` | SQLite 文件路径或其他数据库名称 | SQLite 使用绝对路径；数据库切换前先备份 |
| `DJANGO_TIME_ZONE` | `Asia/Shanghai` | Django 时区 | 按社团所在地设置 |
| `DJANGO_SESSION_COOKIE_SECURE` | `0` / `False` | 是否只通过 HTTPS 发送 Session Cookie | HTTPS 生产设置为 `1` |
| `DJANGO_CSRF_COOKIE_SECURE` | `0` / `False` | 是否只通过 HTTPS 发送 CSRF Cookie | HTTPS 生产设置为 `1` |

### 7.1 开发环境配置

不设置环境变量即可运行本地开发环境：

```bash
.venv/bin/python manage.py runserver
```

此时：

- `DEBUG=True`
- 使用开发专用 `SECRET_KEY`
- 使用 SQLite
- Cookie 的 Secure 标记关闭，方便 HTTP 本地访问
- `ALLOWED_HOSTS` 为空，但 Django 在 `DEBUG=True` 下允许本地开发请求

开发默认值绝不能直接作为生产配置。

### 7.2 生产环境最低配置

下面的命令生成随机密钥并设置必要变量：

```bash
export DJANGO_SECRET_KEY="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(50))')"
export DJANGO_DEBUG="0"
export DJANGO_ALLOWED_HOSTS="example.com,www.example.com"
export DJANGO_SESSION_COOKIE_SECURE="1"
export DJANGO_CSRF_COOKIE_SECURE="1"
export DJANGO_TIME_ZONE="Asia/Shanghai"
```

逐项解释：

- `export NAME=value`：在当前 Shell 及其启动的子进程中设置环境变量。
- `DJANGO_SECRET_KEY=...`：`secrets.token_urlsafe(50)` 生成密码学安全的随机字符串；不要把生成结果写入代码或提交到 Git。
- `DJANGO_DEBUG="0"`：关闭调试页面，避免暴露堆栈和配置。
- `DJANGO_ALLOWED_HOSTS=...`：只允许列出的域名访问；值之间使用逗号，不要写空格依赖解析。
- 两个 `*_COOKIE_SECURE`：强制 Cookie 只通过 HTTPS 发送；只有确认站点已经正确启用 HTTPS 后再设置。
- `DJANGO_TIME_ZONE`：统一时间显示和时间相关业务计算的时区。

设置后执行：

```bash
.venv/bin/python manage.py check --deploy
.venv/bin/python manage.py migrate
```

`check --deploy` 如果仍有 HSTS、SSL 跳转等警告，需要在反向代理和 Django 配置中补充 HTTPS 策略，不能仅靠关闭警告解决。

### 7.3 数据库配置现状

当前代码通过两个环境变量支持最基本的数据库后端和名称：

```bash
export DJANGO_DB_ENGINE="django.db.backends.sqlite3"
export DJANGO_DB_NAME="/var/lib/competition-club/db.sqlite3"
```

当前阶段默认 SQLite，适合开发和小规模使用。切换 PostgreSQL 还需要：

1. 安装 PostgreSQL 驱动，例如 `psycopg`。
2. 在 `config/settings.py` 扩展 `USER`、`PASSWORD`、`HOST`、`PORT` 等连接项。
3. 修改 `DJANGO_DB_ENGINE` 和数据库名称。
4. 在新数据库上执行 `migrate`。
5. 迁移并验证原有数据；不要直接把 SQLite 文件复制成 PostgreSQL 数据库。

这部分暂时不是阶段一的部署实现，架构文档只预留 ORM 平滑迁移方向。

### 7.4 静态文件和媒体文件

当前代码中的固定配置：

| 配置 | 当前值 | 作用 |
|---|---|---|
| `STATIC_URL` | `/static/` | 浏览器访问静态文件的 URL 前缀 |
| `STATIC_ROOT` | `staticfiles/` | `collectstatic` 的收集目录 |
| `STATICFILES_DIRS` | `static/` | 项目自有开发静态文件目录 |
| `MEDIA_URL` | `/media/` | 上传媒体的 URL 前缀 |
| `MEDIA_ROOT` | `mediafiles/` | 上传媒体的磁盘目录 |

阶段三的媒体上传功能：

- 管理员在 `/admin/media/mediafile/` 上传图片或视频。
- 图片允许 `jpg`、`jpeg`、`png`、`webp`、`gif`，最大 10 MB。
- 视频允许 `mp4`、`webm`，最大 500 MB。
- 图片通过 Pillow 解码校验；MP4 检查 `ftyp` 标识，WebM 检查 EBML 文件头。
- 扩展名、文件大小、MIME 类型和二进制签名均不匹配时拒绝保存。
- 媒体由 `ContentPage`、`Award`、`Showcase` 和 `Notice` 通过关联字段引用。
- 开发环境由 Django 提供 `/media/`；生产环境应由 Nginx/对象存储提供，并规划权限、备份和磁盘空间。

阶段三公开路由：

```text
/about/      社团简介快捷地址（读取 slug=about 的已发布页面）
/pages/<slug>/ 通用公开内容页（读取任意已发布页面）
/awards/     历年获奖
/showcase/   成员风采（仅展示 is_active=True）
```

`ContentPage.slug` 是管理员定义的稳定页面标识。管理员新增一个已发布页面（例如 slug 为 `rules`），无需修改代码即可通过 `/pages/rules/` 访问；不存在或未发布的页面返回 404。`/about/` 是保留的友好快捷地址，内部调用同一套 `slug=about` 查询逻辑。

Markdown 正文会先转换为 HTML，再用 Bleach 白名单过滤；脚本和样式块会被移除，避免把管理员输入直接作为 HTML 执行。

阶段四项目组和竞赛功能：

- `/member/projects/`：已登录成员查看项目组、组长和成员。
- `/member/competitions/`：组长和管理员查看竞赛列表。
- `/member/competitions/<id>/register/`：组长为自己的项目组报名，管理员可为任意项目组报名。
- 项目组组长自动纳入该组成员。
- 报名表的项目组和成员选项由前端联动过滤，但后端会再次校验权限和成员归属。
- 同一项目组对同一竞赛只能报名一次。
- 竞赛关闭或超过报名截止时间后不能报名。

阶段五设备功能：

- `/member/equipment/`：查看启用设备和可借数量。
- `/member/equipment/<id>/borrow/`：登记借用，计划归还日期不得早于今天。
- `/member/borrows/`：普通成员查看自己的记录；管理员查看全部记录。
- `/member/borrows/<id>/return/`：本人或管理员登记归还。
- 借用、归还都经过数据库事务和行锁；不可借时不创建记录，重复归还不重复回补库存。
- 管理员在 `/admin/equipment/equipment/` 维护设备；借用记录只能通过归还操作改变状态，不能手工新增或删除。

阶段六平台入口与审计：

- 成员中心和改进顶栏的“操作入口”由 `core.registry` 驱动，不再需要手工同步多个模板。
- 各业务 app 在 `AppConfig.ready()` 注册入口；入口附带排序、Django 权限、仅管理员或自定义业务可见条件。
- 未登录、尚未完成首次改密或未通过权限条件的用户不会看到对应入口；后端接口权限仍然必须独立校验。
- 关键写操作（创建/修改账号、发布通知、维护内容/媒体/项目组/竞赛/设备、竞赛报名、设备借还与成员改密/改资料）会写入 `AuditLog`。
- 审计记录可在 `/admin/core/auditlog/` 只读查询，不允许新增、修改或删除；详情是 JSON，且不记录密码或敏感请求数据。
- Admin 站点标题已定制为“竞赛社团平台管理后台”。

### 7.7 用户认证固定配置

以下不是环境变量，而是当前代码的架构约束：

- `AUTH_USER_MODEL = "accounts.User"`：必须在第一次迁移前确定自定义用户模型；项目已经完成初始迁移，不应中途改回 Django 默认 User。
- `LOGIN_URL = "accounts:login"`：需要登录时的目标地址。
- `LOGIN_REDIRECT_URL = "accounts:member_home"`：普通登录成功后的默认地址；首次登录会由登录视图改为密码页。
- `LOGOUT_REDIRECT_URL = "accounts:home"`：退出后回到公开首页。
- `AUTH_PASSWORD_VALIDATORS`：启用属性相似度、最小长度、常见密码和纯数字密码检查。

---

## 阶段四验收

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py migrate
.venv/bin/python manage.py test projects competitions --verbosity 2
.venv/bin/python manage.py test --verbosity 1
```

阶段四详细标准见 `docs/acceptance-phase4.md`，覆盖项目组、组长权限、竞赛发布、报名成员校验、截止时间和重复报名控制。

## 阶段五验收

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py migrate
.venv/bin/python manage.py test equipment --verbosity 2
.venv/bin/python manage.py test --verbosity 1
```

阶段五详细标准见 `docs/acceptance-phase5.md`，覆盖设备台账、借用、归还、库存一致性、成员记录隔离、管理员代归还和事务保护。

## 阶段六验收

```bash
.venv/bin/python -m compileall -q config accounts notices content media projects competitions equipment core manage.py
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py migrate --check
.venv/bin/python manage.py test core --verbosity 2
.venv/bin/python manage.py test --verbosity 1
```

阶段六详细标准见 `docs/acceptance-phase6.md`，覆盖操作入口注册表、权限过滤、Admin 标题定制、审计日志持久化、只读审计后台和全量回归。

## 8. 日志与调试

### 8.1 日志位置和轮转

日志目录由 `config/settings.py` 中的 `LOG_DIR` 决定，当前是：

```text
logs/django.log
```

日志使用 `RotatingFileHandler`：

- 单文件最大 10 MB
- 最多保留 5 个备份
- 编码 UTF-8
- 同时写入终端和文件

### 8.2 请求日志字段

`RequestLoggingMiddleware` 为每个请求生成 12 位 `request_id`，并记录：

```text
request.start method=GET path=/ query= user=anonymous remote=127.0.0.1
request.end method=GET path=/ status=200 user=anonymous elapsed_ms=...
```

响应头中的 `X-Request-ID` 与日志中的 `request_id` 一致，可用于定位一次请求的全部日志。

### 8.3 查看日志

查看日志文件最后 8000 个字符：

```bash
.venv/bin/python -c "from pathlib import Path; p=Path('logs/django.log'); print(p.read_text(encoding='utf-8')[-8000:] if p.exists() else '日志文件尚未生成')"
```

这个 Python 一行命令的含义：

1. `from pathlib import Path`：导入跨平台路径工具。
2. `Path('logs/django.log')`：指向日志文件。
3. `p.exists()`：判断文件是否存在。
4. `p.read_text(encoding='utf-8')`：按 UTF-8 读取文本。
5. `[-8000:]`：只保留末尾 8000 个字符，避免一次输出过大。
6. 如果文件不存在，输出提示而不是报错。

按关键事件过滤：

```bash
grep -E 'request\.start|request\.end|auth\.login|password_change|profile\.' logs/django.log
```

- `grep`：按文本匹配过滤日志。
- `-E`：启用扩展正则。
- `\.`：匹配字面量句号，避免句号被当作任意字符。

安全要求：不要使用会把密码、完整 POST body 或 Cookie 写入日志的调试代码。登录失败日志只记录用户名，不记录密码。

### 8.4 异常排查顺序

1. 先记录响应中的 `X-Request-ID`。
2. 在 `logs/django.log` 搜索该 ID。
3. 先看 `request.start` 和 `request.end` 的状态、耗时。
4. 如果有 `request.exception`，阅读紧随其后的 traceback。
5. 对认证问题继续搜索 `auth.login`、`password_change`。
6. 对资料问题搜索 `profile.update`。

---

## 9. 常见问题

### 9.1 `No module named django`

原因通常是没有使用虚拟环境中的 Python。执行：

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python manage.py check
```

不要只运行系统的 `python3 manage.py`，除非已经确认系统 Python 安装了同样的依赖。

### 9.2 `no such table`

数据库尚未迁移或使用了错误的数据库路径：

```bash
.venv/bin/python manage.py showmigrations
.venv/bin/python manage.py migrate
```

同时检查 `DJANGO_DB_NAME` 是否指向预期文件。

### 9.3 修改模型后测试提示有未生成迁移

先生成迁移，再检查：

```bash
.venv/bin/python manage.py makemigrations
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py migrate
```

### 9.4 `DisallowedHost`

请求中的 Host 不在 `ALLOWED_HOSTS`：

```bash
export DJANGO_ALLOWED_HOSTS="127.0.0.1,localhost,example.com"
```

生产环境不要用 `*` 作为长期配置。

### 9.5 端口已经被占用

换一个端口启动：

```bash
.venv/bin/python manage.py runserver 127.0.0.1:8765
```

### 9.6 登录后一直回到改密页

这是设计行为，检查：

1. 新密码是否真正提交成功。
2. 页面是否提示密码校验错误。
3. 数据库中账号的 `must_change_password` 是否为 `False`。
4. `logs/django.log` 中是否有 `auth.password_change.success`。

管理员重置密码后再次回到改密页是预期行为。

### 9.7 `check --deploy` 有安全警告

开发环境下部分警告是因为：

- `DEBUG=True`
- Cookie Secure 未开启
- HSTS 未配置
- SSL 强制跳转未配置
- `ALLOWED_HOSTS` 为空

不要用 `SILENCED_SYSTEM_CHECKS` 掩盖生产问题。先完成 HTTPS 反向代理，再设置生产环境变量并重新执行 `check --deploy`。

### 9.8 CSRF 失败

确认：

- 所有 POST 表单包含 `{% csrf_token %}`。
- 生产站点使用 HTTPS 时 `DJANGO_CSRF_COOKIE_SECURE=1`。
- 反向代理没有错误地丢弃 `Origin`、`Referer` 或 Cookie。
- 如果使用新的域名，按实际域名检查 CSRF Trusted Origin 配置；当前阶段还没有通过环境变量配置该项。

---

## 10. 变更和提交规则

修改模型、配置或认证流程后，按以下顺序执行：

```bash
.venv/bin/python -m compileall -q config accounts manage.py
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations
.venv/bin/python manage.py migrate
.venv/bin/python manage.py test --verbosity 1
```

各命令的目的：

1. `compileall`：先排除 Python 语法错误。
2. `check`：排除 Django 配置错误。
3. `makemigrations`：让数据库结构变化有可追踪的迁移文件。
4. `migrate`：在本地数据库应用迁移。
5. `test`：验证行为没有回归。

测试通过后再提交代码。阶段一的完成标准不是“服务器能启动”，而是所有验收测试、迁移检查和配置检查均通过。
