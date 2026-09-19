# 开发指南

面向继续开发本项目的开发者：目录结构、环境配置、常用命令、测试与验收口径、日志调试和常见问题。命令默认在项目根目录执行。

> 设计/数据模型/权限等**架构说明**见 [`architecture.md`](architecture.md);**部署**见 [`deploy.md`](deploy.md)。

---

## 1. 项目结构

```text
.
├── manage.py                         # Django 命令入口
├── requirements.txt / requirements-prod.txt
├── config/                           # 项目配置包
│   ├── settings.py                   # 全局配置与环境变量读取（数据库固定 PostgreSQL）
│   ├── urls.py                       # 根路由
│   ├── admin.py                      # Admin 站点标题定制
│   ├── middleware.py                 # 请求日志、强制改密
│   ├── logging.py / asgi.py / wsgi.py
├── accounts/                         # 账号与成员资料
│   ├── models.py                     # User（含 must_change_password、is_reviewer、is_preliminary_reviewer、is_super_reviewer）、Profile（含特长 specialty）
│   ├── roles.py                      # 身份展示口径（管理员／联系人／成员／无组）
│   ├── forms.py / views.py / urls.py / admin.py
│   ├── signals.py                    # Profile 自动创建、认证日志、登录时的待办提醒（初审/评审分开报数）
│   └── tests.py
├── notices/                          # 通知（public / internal / contacts）
│   ├── models.py                     # Notice
│   ├── visibility.py                 # 成员可见通知的唯一判定点
│   ├── views.py / urls.py / member_urls.py / admin.py / forms.py
│   └── tests.py
├── content/                          # 公开展示：简介、获奖、成员风采
│   ├── models.py / views.py / urls.py / admin.py
│   ├── templatetags/rendering.py     # Markdown 安全渲染
│   └── tests.py
├── media/                            # 图片/视频媒体库
│   ├── models.py                     # MediaFile
│   ├── validators.py                 # 类型、大小、签名校验
│   └── tests.py
├── projects/                         # 项目组与联系人
│   ├── models.py                     # ProjectGroup、ProjectAdvisor（指导老师，每组至多 3 位）、GroupJoinRequest、GroupCreateRequest（创建项目组申请）、ProjectContact（代理）
│   ├── permissions.py                # 联系人/成员/组可见性/创建申请审核人的唯一判定点
│   ├── services.py                   # 入组审核、创建项目组的申请与审核、移除成员、转让联系人等事务操作
│   ├── validators.py                 # 项目书文件校验
│   ├── forms.py / views.py / urls.py / admin.py
│   └── tests.py
├── competitions/                     # 竞赛与报名
│   ├── models.py                     # Competition、CompetitionRegistration（含 team_leader）
│   ├── permissions.py                # 报名权限（薄封装 projects.permissions）
│   ├── context_processors.py         # 报名入口可见性
│   ├── forms.py / views.py / urls.py / admin.py
│   └── tests.py
├── reviews/                          # 项目书同行评审（初审关卡 + 评审）
│   ├── models.py                     # ProjectSubmission、ReviewTask（初审/评审同表，stage 区分）、ArchivedProposal、ReviewerLeave
│   ├── lifecycle.py                  # 轮次状态机（迁移表 + 唯一写入点 transition()）与两道关的口径 STAGES
│   ├── permissions.py                # 评审资格、「凭评审身份能否看这一组」与队列页准入（管理员无资格亦可）的唯一判定
│   ├── panels.py                     # 队列页／项目组详情页／成员中心三处页面上下文的装配入口（含管理员的创建申请待办）
│   ├── services.py                   # 送审、抽人（eligible_holders/_draw_tasks）、交卷（submit_verdict）、汇总与归档、超级评审敲定、管理员改派（reassign_task）、请假、待办计数
│   ├── forms.py / views.py / urls.py / admin.py
│   └── tests/                        # 测试按功能分模块（用例多，见 §5）
│       ├── factories.py              # 造对象：用户/角色、项目组、上传文件
│       ├── base.py                   # ReviewTestCase：临时 MEDIA_ROOT + 推进轮次的动作
│       └── test_*.py                 # 送审 / 结论与归档 / 页面 / 初审 / 请假 / 提醒 / 改派 / 超级评审 / 后台删整轮
├── equipment/                        # 设备台账与借用
│   ├── models.py                     # Equipment、EquipmentBorrow
│   ├── services.py                   # 事务化借用/归还与库存更新
│   ├── forms.py / views.py / urls.py / borrow_urls.py / admin.py
│   └── tests.py
├── core/                             # 平台核心
│   ├── registry.py                   # 操作入口注册表
│   ├── models.py / audit.py          # AuditLog 与统一审计函数
│   ├── context_processors.py         # 注入操作入口与顶栏当前栏目
│   ├── stats.py                      # 首页概览计数
│   ├── templatetags/files.py         # 文件路径过滤器（文件名 / 扩展名）
│   └── tests.py
├── templates/  static/  mediafiles/  logs/
├── static/css/app.css                # 全站设计系统（唯一视觉来源）
├── static/css/admin.css              # Django Admin 配色，与 app.css 同色值
├── docs/                              # architecture.md / development.md / deploy.md
├── deploy/                            # 部署工件：install.sh / deploy.sh / backup.sh / *.service / *.timer / nginx / env.template
└── env.local.sh                       # 本地开发配置（.gitignore 忽略）
```

本机生成内容（`.venv/`、`__pycache__/`、`logs/`、`mediafiles/`、`staticfiles/`、`env*.sh`）不提交版本库，规则见 `.gitignore`。根目录 `社团评审系统_发布版.zip` 是历史压缩包，不参与运行。

### 1.1 样式与模板约定

页面外观集中在 `static/css/app.css`，模板不写行内样式、不写 `<style>`：

- **令牌**：颜色、字体、宽度都取自文件顶部的 `:root` 变量；调整配色只改这一处。
- **骨架类**：`topbar` / `pagehead`+`path` / `spec`（页面级数字条）/ `panel`+`panel-head`+`panel-body` / `frame` / `split`（左右分栏）/ `col-narrow`、`col-center`（窄栏与居中）。
- **组件类**：`btn`（`-primary`/`-danger`/`-sm`/`-block`）、`chip`（`-pin`/`-ok`/`-warn`/`-off`/`-on`）、`table-wrap`、`field`、`dl`、`prose`（Markdown 渲染结果）、`entries`/`entry`、`todo`、`queue`/`qitem`、`rounds`、`empty`、`flash`。
- **字体**：只用系统字体栈（Noto Sans SC → 苹方 → 微软雅黑），不加载外部字体；等宽字只用于编号、日期、文件规格这类真值，不做装饰。
- **动效**：`.reveal` 只在页面载入时编排一次淡入，并遵守 `prefers-reduced-motion`；不要给每个区块加逐条动画。
- 表单控件由元素选择器统一着色，新增字段无需加 class。`templates/django/forms/widgets/clearable_file_input.html` 覆盖了 Django 的文件控件默认模板，与 `app.css` 的 `.file-current` 一族配套。

## 2. 依赖

`requirements.txt`：

| 依赖 | 作用 |
|---|---|
| `Django>=5.2,<5.3` | Web 框架、ORM、认证、Session、Admin、迁移、模板、测试 |
| `djangorestframework>=3.16,<3.17` | 为后续 API 预留，当前不做主要渲染 |
| `bleach>=6.2,<7` | 富文本 HTML 白名单过滤 |
| `markdown>=3.8,<4` | Markdown 渲染 |
| `Pillow>=11.3,<12` | 校验上传图片真实格式 |
| `psycopg[binary]>=3.2,<4` | PostgreSQL 驱动 |

`requirements-prod.txt` 仅增 `gunicorn`。版本写成"下限+上限"，允许补丁更新、避免未验证的主版本跳变。

## 3. 环境与配置

### 3.1 本地开发

数据库**固定为 PostgreSQL**（Django 5.2 要求 ≥14），连接参数写在根目录 `env.local.sh`：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

source env.local.sh          # 必须：不加载会因缺少库名/账号/密码连接失败
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver
```

访问：首页 `/`、成员登录 `/login/`、管理后台 `/admin/`。

> 本应用已移除 SQLite。任何 `migrate` / `test` / `runserver` 前都要先 `source env.local.sh`；看到 `fe_sendauth: no password supplied` 之类错误即是忘了 source。

### 3.2 环境变量（`config/settings.py` 读取）

| 变量 | 默认值 | 作用 |
|---|---|---|
| `DJANGO_SECRET_KEY` | 开发专用固定串 | 签名/Session/令牌密钥；**生产必须**随机长串 |
| `DJANGO_DEBUG` | `1` | 调试模式；生产设 `0` |
| `DJANGO_ALLOWED_HOSTS` | 空 | 允许的 Host，逗号分隔 |
| `DJANGO_DB_NAME` | `club702_dev` | PostgreSQL 库名 |
| `DJANGO_DB_USER` / `DJANGO_DB_PASSWORD` | 空 | PostgreSQL 账号/密码 |
| `DJANGO_DB_HOST` / `DJANGO_DB_PORT` | `127.0.0.1` / `5432` | PostgreSQL 地址/端口 |
| `DJANGO_TIME_ZONE` | `Asia/Shanghai` | 时区 |
| `DJANGO_SESSION_COOKIE_SECURE` / `DJANGO_CSRF_COOKIE_SECURE` | `0` | 仅 HTTPS 发送 Cookie；生产设 `1` |

生产投放方式（占位符 + 校验）见 [`deploy.md`](deploy.md)。

### 3.3 代码内固定配置

| 配置 | 值 | 作用 |
|---|---|---|
| `STATIC_URL` / `STATIC_ROOT` / `STATICFILES_DIRS` | `/static/` / `staticfiles/` / `static/` | 静态文件 |
| `MEDIA_URL` / `MEDIA_ROOT` | `/media/` / `mediafiles/` | 上传媒体 |
| `AUTH_USER_MODEL` | `accounts.User` | 已迁移，不可中途更换 |
| `LOGIN_URL` / `LOGIN_REDIRECT_URL` / `LOGOUT_REDIRECT_URL` | `accounts:login` / `accounts:member_home` / `accounts:home` | 登录跳转 |
| `AUTH_PASSWORD_VALIDATORS` | 相似度/最小长度/常见密码/纯数字 | 密码强度 |

**媒体上传限制**：图片 `jpg/jpeg/png/webp/gif` ≤10MB（Pillow 解码校验）；视频 `mp4`（查 `ftyp`）/`webm`（查 EBML 头）≤500MB。项目书与评审人的批注版项目书 `doc/docx/pdf` ≤20MB（扩展名 + 文件头签名，复用同一校验器）。扩展名、大小、MIME、签名任一不符即拒绝。

## 4. 常用命令

| 目的 | 命令 |
|---|---|
| 配置检查 | `.venv/bin/python manage.py check` |
| 生产安全自检（本地有警告属正常） | `.venv/bin/python manage.py check --deploy` |
| 检查是否遗漏迁移（预期 `No changes detected`） | `.venv/bin/python manage.py makemigrations --check --dry-run` |
| 生成迁移 | `.venv/bin/python manage.py makemigrations` |
| 应用迁移 | `.venv/bin/python manage.py migrate` |
| 查看迁移状态 | `.venv/bin/python manage.py showmigrations` |
| 全量测试 | `.venv/bin/python manage.py test` |
| 单模块测试 | `.venv/bin/python manage.py test reviews projects` |
| 单个测试类/方法 | `.venv/bin/python manage.py test accounts.tests.MemberAuthenticationAcceptanceTests` |
| 语法检查 | `.venv/bin/python -m compileall -q config accounts notices content media projects competitions reviews equipment core manage.py` |
| 收集静态文件 | `.venv/bin/python manage.py collectstatic --noinput` |

测试使用临时测试库，不会污染开发库 `club702_dev`。服务端渲染的本地冒烟可用 `runserver 127.0.0.1:8765 --noreload`。

## 5. 测试与验收

**验收 = 下面三条全部通过**：

```bash
source env.local.sh
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run   # 预期 No changes detected
.venv/bin/python manage.py test                               # 全绿
```

测试按模块分布在各 app 的 `tests.py`，覆盖的验收要点：

**`reviews` 例外**：它的用例最多（169 条），因此按功能拆成 `reviews/tests/` 包，一个模块一个主题——送审规则、结论与归档、评审页面、初审关卡、请假、待办提醒、改派、超级评审、后台删整轮。共用件只有两处：`factories.py`（造对象）与 `base.py`（`ReviewTestCase`：临时 MEDIA_ROOT + `_open_round`/`_pass_preliminary`/`_submit` 三个推进轮次的动作）。夹具（谁是评审人、各有几名）**刻意留在各个类自己的 `setUp`**：送审类型决定名额，而名额是「恰好抽到谁」这类断言的前提，由基类统一发放夹具会让这些断言随候选人数变化而时灵时不灵。跑单个模块用 `manage.py test reviews.tests.test_preliminary`。

| 模块 | 验收要点 |
|---|---|
| `accounts` | 管理员发放账号/重置密码；首次登录强制改密、改密后解锁；资料维护（姓名/学号/学院/专业/特长/联系方式）；无注册、无自助找回；审计与日志不含明文密码；非 staff 不能进后台 |
| `notices` | `public`/`internal`/`contacts` 三种范围隔离；`internal` 按 auth 用户组、`contacts` 按项目组联系人；置顶排序；公开路由不泄漏内部/联系人通知；未授权详情 404；未改密拦截 |
| `content` / `media` | 已发布才公开；按 slug 直连的未发布页 404，而顶栏固定入口 `/about/` 未发布时显示空状态；Markdown 经 bleach 白名单；图片/视频扩展名+大小+签名校验 |
| `projects` | 联系人由 `leader` 计算；无组员看全部可申请、组员只看自己的组、联系人看全部并管理自己的组；申请→审核入组；拒绝后可重申；申请创建项目组（任一管理员在「评审」页同意即建组，其余管理员的待办随之消失）；移除成员；联系人转让后原联系人保留为成员；改组介绍与学院/指导老师（指导老师每组至多 3 位，空槽位不占位并自动补齐；上限在数据库层由槽位唯一约束 + CHECK 兜住，服务层另有一道）；非联系人管理页 403 |
| `competitions` | 竞赛列表所有登录成员可见；仅项目组联系人报名（限自己的组）；参赛成员与竞赛组长须属该组且组长在参赛成员内；重复报名/截止校验；报名修改与放弃；跨组越权拒绝 |
| `equipment` | 借用限项目组成员（入口隐藏 + 视图 403）；库存事务 + 行锁不超借；仅见本人记录；归还回补、重复归还不重复回补；管理员代还；被移出组后仍可归还 |
| `reviews` | **任务是一张表**（`ReviewTask`，`stage` 区分初审／评审：一人一轮一席、每轮至多一条初审、超级评审那票只属于评审阶段三条约束在数据库层）；状态机与两道关的口径收敛在 `lifecycle.py`（改状态一律经 `transition()`），页面上下文由 `panels.py` 统一装配，评审判定在 `permissions.py`；任一评审资格（`is_reviewer`／`is_preliminary_reviewer`／`is_super_reviewer`）驱动「评审」入口（管理员即使没有资格也进得来——项目组创建申请汇总在这里），队列按各自那一侧渲染三档（初审：待初审／已完成的初审／已释放的初审；评审：待评审／已完成的评审／已释放的评审）；送审先落到 1 名初审人手上（`preliminary_pending`），此时没有任何评审任务；抽初审人只从有初审资格、启用中、未请假、非提交人/本组成员里取（`eligible_holders(stage="preliminary")`），一个都没有即拒绝送审；提交时另做**评审人容量预检**（不足即拒绝开这一轮，预检排除本轮初审人——初审人不能占评审席位），避免开出一轮谁也推进不了的送审；初审「通过」在同一事务内按送审类型抽齐评审人（竞赛类 3 / 大创中期·结题 2 / 大创立项 1）并转 `pending`，「需修改」则本轮直接 `needs_revision`、不分配评审人；通过时若池子已缩水（有人开始请假或资格被撤）则整次回滚（结论不落库、任务仍待初审，可原地重试），提示语指向「稍后重试或请管理员补充评审人」；**本人初审通过的那一轮不再抽到本人**（`_eligible_pool` 统一排除，抽人、容量预检与改派同源）；初审没有批注版，结论与评审共用同一对取值；全部评审人均通过→方案通过，任一需修改→可修改后重提；批注版项目书选填，通过后按上传者归档（未上传不产生记录、重复汇总不重复归档）；批注与归档文件仅 staff/组内/被分配评审人可下载且文件名不含身份；初审人、评审人、超级评审一律匿名（页面只写「初审」「评审人 N」「超级评审」），初审打回的轮次在「方案状态」里指向初审意见而不是不存在的评审意见；具备评审或初审资格者可登记请假窗口，窗口内两种抽取与容量预检都排除他且 `ends_at` 一到自动恢复（无定时任务），管理员可在 Admin 列表直接改时间；手上有未完成初审/评审时登录即提醒（两种分开报数），成员中心顶部常驻待办卡片（计数不含请假、撤销资格者不提醒、发送用 fail_silently 以免影响登录）；同一项目组同时只允许一个未结束的轮次（初审中也算未结束，判据是 `OPEN_STATUSES` 而不是 `status == pending`）；`can_view_group` 的各项授权取**并集**（staff／组员／本轮初审人／被分配任务者／有未结束轮次时的超级评审），多资格账号不会因为走了超级评审那一支而丢掉自己任务带来的可见性；管理员可在 Admin 详情页改派「待处理且该轮未判结论」的评审任务与「待初审且该轮仍在初审中」的初审任务（候选与抽人同源（`eligible_holders(stage=…)`）、已判结论的记录仍只读、**且账号确实持有该模型的修改权限**——只读观察者不能改派、禁止新增与删除单条任务，但整轮可在后台删除（豁免两项级联检查，已归档的轮次被 PROTECT 挡住，删除写审计）、写入经服务层并审计）；超级评审（`User.is_super_reviewer`）可在「评审」看到全部进行中的轮次（含初审中）并一票通过/打回，不经结论汇总（否则普通评审人的「需修改」会顶回该决定），敲定时等待中的评审与初审任务都变为 `released`；`submit_verdict()` 因此是「非 pending 一律拒绝」，否则被释放者仍能提交并改写记录；可否行使由 `override_blocker()` 一处判定（返回具体原因，None 为可行使），表单显隐、拒绝信息与队列页的「不可行使」标注都取自它，提交人/组成员/已在本轮持有任务（含初审任务）者不得行使 |
| `core` | 操作入口注册表按登录/改密/权限/自定义条件过滤；审计只读；Admin 标题定制 |

评估某项改动是否合格：先补齐迁移并让 `check`、`makemigrations --check`、`test` 全过；测试通过后再提交。

## 6. 日志与调试

- 日志文件 `logs/django.log`，`RotatingFileHandler`，单文件 10MB、保留 5 份、UTF-8，同时输出终端与文件。
- 每个请求生成 12 位 `request_id`，响应头 `X-Request-ID` 与日志一致，用于串联一次请求：

  ```text
  request.start method=GET path=/ query= user=anonymous remote=127.0.0.1
  request.end method=GET path=/ status=200 user=anonymous elapsed_ms=...
  ```

- 按事件过滤：`grep -E 'request\.start|request\.end|auth\.login|password_change|profile\.' logs/django.log`
- 排查顺序：记下响应头 `X-Request-ID` → 在日志中搜索该 ID → 看 `request.start`/`request.end` 的状态与耗时 → 如有 `request.exception` 读紧随的 traceback。
- 安全：不要把密码、完整 POST body 或 Cookie 写入日志；登录失败只记录用户名。

## 7. 常见问题

| 现象 | 处理 |
|---|---|
| `No module named django` | 用了系统 Python；改用 `.venv/bin/python manage.py ...` |
| `fe_sendauth: no password supplied` / 连接失败 | 忘了 `source env.local.sh`（数据库固定 PostgreSQL，无 SQLite 回退） |
| `no such table` | 未迁移或连错库：`showmigrations` → `migrate`，并核对 `DJANGO_DB_*` |
| 改了模型却提示有未生成迁移 | `makemigrations` → `makemigrations --check --dry-run` → `migrate` |
| 登录后一直回到改密页 | 设计行为：确认新密码提交成功、库中 `must_change_password=False`、日志有 `password_change.success` |
| `DisallowedHost` | 把访问 IP/域名补进 `DJANGO_ALLOWED_HOSTS`（不带端口） |
| 端口被占用 | 换端口：`runserver 127.0.0.1:8765` |
| `check --deploy` 有安全警告 | 开发环境预期；生产完成 HTTPS 后配置环境变量再跑，勿用 `SILENCED_SYSTEM_CHECKS` 掩盖 |
| CSRF 失败 | 表单含 `{% csrf_token %}`；HTTPS 下 `DJANGO_CSRF_COOKIE_SECURE=1`；反代勿丢 `Origin`/`Referer`/Cookie |

## 8. 变更与提交

改动模型、配置或认证流程后按序执行：`compileall` → `check` → `makemigrations` → `migrate` → `test`。全部通过后再提交；迁移文件必须与模型代码一起提交。
