# config 包

> 项目配置包：进程级装配——环境变量与设置、根路由、中间件链、后台站点定制、日志配置、
> WSGI／ASGI 入口。它管「整个进程以什么姿态运行」，**不管任何业务**：没有表、没有权限判定、
> 没有服务层，也不在 `INSTALLED_APPS` 里（所以它连 models 都没有）。
> 业务规则在各自 app，config 只决定它们挂在什么地址、按什么顺序、在什么安全开关下运行。

**什么时候看**：加或调环境变量、动中间件顺序与安全响应头、改根路由或双语前缀、
动 Cookie／HTTPS／HSTS／上传体积上限这类平台级开关、改日志分级、定制后台站点外观的时候。

---

## 1. 职责与边界

**负责**（都在 `config/` 下）：

| 东西 | 代码坐标 |
|---|---|
| 设置与环境变量读取（`env_bool`）、测试进程判定（`running_tests`）、生产自检守卫 | `settings.py` |
| 根路由、`/en/` 双语前缀、`DEBUG` 下公开媒体的投放 | `urls.py` |
| 三个中间件：请求日志、安全响应头、首次登录强制改密 | `middleware.py` |
| 后台站点标题与「身份管理」分组的聚合 | `admin.py` |
| 日志格式化器（给每条记录补 `request_id`） | `logging.py` |
| 服务器入口 | `wsgi.py`、`asgi.py`（生产只用前者） |
| 设置层判定逻辑的单测 | `tests.py` |

**明确不做**——它们各自落在哪：

| 不在这里 | 落在哪 |
|---|---|
| 任何表结构、业务判定与写操作 | **本包没有 `models.py` / `permissions.py` / `services.py`**，不在 `INSTALLED_APPS` 里 |
| 业务路由 | 各 app 的 `urls.py`；`config/urls.py` 只做 `include` 与命名空间 |
| 登录锁定的计数、冷却与判定 | django-axes；config 只给 `AXES_*` 阈值，并把 `AXES_CLIENT_IP_CALLABLE` 指到 `core.audit.get_client_ip`、`AXES_LOCKOUT_CALLABLE` 指到 `accounts.axes.lockout_response` |
| 受保护件的存储与取件 | `core/storage.py` 与各 app 的取件视图；config 只定义两个媒体根 |
| 用户可见文案 | 模板与 `panels`（前台一律 `gettext`）。config 里只有后台标题，后台**不在双语范围** |
| 部署动作本身 | `deploy/*.sh`、systemd 与 Nginx 模板；config 只提供它们要读的环境变量、以及 `check --deploy` 要过的那套设置 |
| 静态与媒体目录的搬运 | `core/migrations/0002_rehome_protected_uploads`；config 的职责只是把两个根**分开**（见 §3） |

**依赖方向**：config → 各 app（`include` 各家的 `urls`，以及 `accounts.axes`、`core.audit` 两个回调名），
反向是各 app 读 `django.conf.settings`（`PRIVATE_MEDIA_ROOT`、`AUTH_USER_MODEL`、`TRUST_FORWARDED_FOR`……）。
config 是 app 名字最集中的一处：新增一个前台 app，要在 `config/urls.py` 的 include 列表里加一行并给它命名空间；
要让它的功能出现在成员中心，还得到 `core.registry` 登记操作入口（那一步不在本包）。

---

## 2. 关键接口与失败模式

| 入口 | 语义 | 前置条件 | 失败模式 |
|---|---|---|---|
| `settings.running_tests(argv=None)` | 这次进程是不是 `manage.py test`——判定是**命令行参数里有没有一个整词等于 `test`** | 无 | 判定写坏（如只看 `sys.argv[1]`）＝生产静默落到 MD5 哈希，**没有任何报错**；`config/tests.py` 的用例钉住它认哪些、不认哪些 |
| `settings.env_bool(name, default)` | 布尔环境变量：只认 `1/true/yes/on`（忽略大小写与首尾空白） | 变量没设时才用 `default` | 设成 `0`／`false`／`off`／拼错的值一律是 `False`——**不存在「值非法」这个报错**，写错了只会安静地按关闭处理 |
| 整型与路径类环境变量（`DJANGO_SECURE_HSTS_SECONDS`、`DJANGO_PRIVATE_MEDIA_ROOT`） | 直接 `int()` / `Path()` | 同上 | `int()` 收到非数字 → **导入期 `ValueError`，进程起不来**；`Path()` 不做 `resolve`，填相对路径时它相对**进程的工作目录**，不是项目根 |
| 列表类（`DJANGO_ALLOWED_HOSTS`、`DJANGO_CSRF_TRUSTED_ORIGINS`） | 逗号分隔，逐项 `strip` 后丢掉空项 | 同上 | 空串（不设）得到空列表；`ALLOWED_HOSTS` 为空且 `DEBUG=False` 时一切请求 `DisallowedHost`，由 `check --deploy` 的 `security.W020` 在上线前拦下 |
| `SECRET_KEY` 守卫（`settings.py` 末尾） | `DEBUG=False` 且仍是源码里的开发默认串 → 拒绝启动 | 模块导入期 | 抛 `ImproperlyConfigured`。**起不来是响的，起得来但会话可被伪造才是危险的**——所以这条不做成告警 |
| `config.middleware.RequestLoggingMiddleware` | 每个请求生成 12 位 `request_id`，记 `request.start` / `request.end` / `request.exception`，把 id 塞进响应头 `X-Request-ID` | 必须排在 `AuthenticationMiddleware` 之后（start 行里才有用户名） | 异常路径上只补一条 `request.exception` 就**重新抛出**，不吞异常——500 仍走 Django 的常规路径（`django.request` 记 ERROR） |
| `config.middleware.SecurityHeadersMiddleware` | 补 `Content-Security-Policy` 与 `Permissions-Policy`；`/admin/` 用放宽版（两处 `'unsafe-inline'`） | 挂在 `MIDDLEWARE` 里 | 漏挂＝测试红；**CSP 收紧写坏的表现是页面静默失效**（按钮没反应、样式没加载），没有报错可查；用 `setdefault` 写入，视图自己发过就不覆盖 |
| `config.middleware.ForcePasswordChangeMiddleware` | `must_change_password=True` 的用户，除改密页与登出页外一律 302 回改密页（带 `next`） | 用 `process_view`，要求 `request.user` 已解析 | 白名单按 **`request.path` 精确比对**，所以连 `/admin/` 也不放行；未匹配的 URL 走不到它（404 先发生，不会把人重定向到一个不存在的页面） |
| `config.urls.urlpatterns` | `/admin/` 一条 + 前台全部路由包在 `i18n_patterns` 里；`DEBUG=True` 时额外挂 `MEDIA_ROOT` | 双语要求 `LocaleMiddleware` 在链上 | 新增 app 有两种写错法：**漏了 include** → URL 根本没注册（`reverse` 报 `NoReverseMatch`，一访问就炸）；**include 了但写在 `i18n_patterns` 之外** → 页面能开、`reverse` 也解析得动，只是没有 `/en/` 版——这一种不报错，只能靠 `/en/` 下点一遍发现。受保护根**刻意不挂**，本地也取不到直链 |
| `config.admin._install_role_section(admin.site)` | 覆写 `AdminSite.get_app_list`，把六张名册提成置顶的「身份管理」分组 | **靠 `config/urls.py` 顶部 `from config import admin as platform_admin` 的副作用导入**才执行——`config` 不在 `INSTALLED_APPS` 里，Django 不会替它自动加载 | 删掉那行 import＝后台标题与分组静默回到 Django 默认，没有任何报错；`ROSTER_MODELS` 里的模型改名后不报错，只是悄悄落回它自己的 app 分组（没有测试盯着这两处） |
| `config.logging.RequestContextFormatter` | 给没有 `request_id` 的记录补 `-`，让启动、迁移日志也能套同一套格式 | 用于 `detailed` 格式串 | 不补的话格式串里的 `{request_id}` 取值失败，`logging` 会把整条记录丢掉并在 stderr 打一段 `--- Logging error ---` |
| `config.wsgi.application` / `config.asgi.application` | 标准服务器入口，默认 `DJANGO_SETTINGS_MODULE=config.settings` | — | 生产只用 WSGI（systemd 跑 `gunicorn config.wsgi:application`）；ASGI 入口在仓库里，但没有任何部署形态用它 |

---

## 3. 状态与不变量

改动时**不能破坏**的硬约定：

- **`AUTH_USER_MODEL = "accounts.User"` 不可中途更换**：所有业务表都以它为外键、迁移已按它建表，
  换它等于重建全库。加字段要在 `accounts` 里加，config 只负责指过去。
- **两个媒体根刻意分家**：`MEDIA_ROOT`（`mediafiles/`）公开、Nginx 的 `/media/` 直出；
  `PRIVATE_MEDIA_ROOT`（`protected_media/`）**刻意不在前者之下**，没有任何 HTTP 路径能直接取到它，
  取件一律经视图做权限判定（`docs/development.md` §3.3）。`config/urls.py` 在 `DEBUG=True` 时只挂
  `MEDIA_ROOT`，受保护根本地也不挂——**「开发能直连、线上不能」这种差异会掩盖问题**。
  备份要同时收两个目录（`deploy/backup.sh` 与 `deploy/deploy.sh` 都已这么做）。
- **`/admin/` 不在双语名单里**：地址固定 `/admin/`，后台文案写中文原样、不进 `.po`。
  前台用 `i18n_patterns(prefix_default_language=False)`，**中文地址与改造前逐字节相同**；
  **地址即语言**，与浏览器语言、Cookie 都无关（`docs/development.md` §3.4）。
- **静音的检查项跟着开关走**：`SILENCED_SYSTEM_CHECKS` 由两个条件推导——`security.W004` 跟随
  `SECURE_HSTS_SECONDS`、`security.W008` 跟随 `SECURE_SSL_REDIRECT`。开关一打开，告警自动回来。
  **不要把它改成写死的清单**：一条永远为真的告警会让「有告警即失败」的上线门禁变成摆设。
- **两个「默认关」是刻意的**：`SECURE_SSL_REDIRECT` 与 `SECURE_HSTS_SECONDS` 默认关闭，理由与开启条件
  在 `docs/deploy.md` §2.5；HSTS 一旦生效，浏览器会在有效期内拒绝一切非 https 访问，证书出问题就锁死站点。
- **安全默认值站在安全那一侧**：`SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE` 默认开（唯一例外是纯 http
  部署，要在 `env.sh` 显式改 0，否则浏览器不带 Cookie、谁都登不进来）；`SESSION_COOKIE_AGE` 是 3 天且
  `SESSION_EXPIRE_AT_BROWSER_CLOSE=True`——对装着实名信息与评审机密的站来说，这是取舍不是遗漏。
- **认证后端的顺序不能反**：`AxesStandaloneBackend` 在 `ModelBackend` 之前——先看这个账号／IP 是否已锁，
  锁着就直接拒绝，**正确的口令同样不放行**。反过来「锁定」就只是一句提示。
- **`AXES_RESET_ON_SUCCESS = False`**：成功登录只清该账号的失败计数，**不清 IP 那一格**；否则知道口令的人
  可以隔几次成功登一次把 IP 计数刷掉。锁定期间也不刷新计时（否则持续尝试能把合法用户永久关在门外）。
- **上传体积上限显式写死**：`FILE_UPLOAD_MAX_MEMORY_SIZE` 与 `DATA_UPLOAD_MAX_MEMORY_SIZE` 都是 5 MB，
  不让它们随 Django 版本漂；视频能到几百 MB，靠的是文件上传走流式解析（超限落临时文件），
  整体上限另由 Nginx 的 `client_max_body_size` 与各 app 的校验管。
- **前台 CSP 不含 `'unsafe-inline'`**：模板不写内联 `<script>`、不写行内样式，页面脚本放 `static/js/`；
  唯一放宽的是 `/admin/`（Django admin 模板自带内联脚本与样式，收不掉）。**今后每收紧一条 CSP 指令，
  都要在真实浏览器里把相关页面点一遍**——强制 CSP 拦错是静默的。
- **`INSTALLED_APPS` 里的 `django.contrib.postgres` 只为函数与查找**（获奖判重用的 pg_trgm 相似度）：
  无模型、无迁移，别把业务模型挂到它下面。
- **`DEFAULT_AUTO_FIELD = BigAutoField`**：主键一律数据库自增整数（地址里的 `<id>` 就是它）。
- **登录跳转三兄弟指向 accounts 的 URL 名**：`LOGIN_URL` / `LOGIN_REDIRECT_URL` / `LOGOUT_REDIRECT_URL`
  改路由名时要同步；它们被 `@login_required` 与认证视图在框架层读取。

---

## 4. 数据流与时序

### 一次请求穿过中间件

`MIDDLEWARE` 的顺序就是语义，从外到内：

| # | 中间件 | 为什么在这个位置 |
|---|---|---|
| 1 | `django.middleware.security.SecurityMiddleware` | 最外层，HSTS／SSL 跳转／nosniff／Referrer-Policy |
| 2 | `config.middleware.SecurityHeadersMiddleware` | 贴在最外层之一：后面任何视图返回的响应都带上 CSP 与 `Permissions-Policy`，且用 `setdefault` 不覆盖视图自己发的 |
| 3 | `django.contrib.sessions.middleware.SessionMiddleware` | |
| 4 | `django.middleware.locale.LocaleMiddleware` | 按地址上的 `/en/` 前缀激活语言；**必须排在 Session 之后、Common 之前**（Django 的要求） |
| 5 | `django.middleware.common.CommonMiddleware` | |
| 6 | `django.middleware.csrf.CsrfViewMiddleware` | |
| 7 | `django.contrib.auth.middleware.AuthenticationMiddleware` | 到这一步 `request.user` 才存在 |
| 8 | `axes.middleware.AxesMiddleware` | 把 axes 在口令校验前抛的「已锁定」变成 403 页；**少了它这个异常会直接冒到 500** |
| 9 | `config.middleware.RequestLoggingMiddleware` | 排在 Auth 之后：`request.start` 行才能记出用户名；生成的 `request_id` 被审计与全站日志的 `extra={"request_id": ...}` 读取 |
| 10 | `config.middleware.ForcePasswordChangeMiddleware` | 在请求日志之内，所以被拦下的 302 也会留下日志 |
| 11 | `django.contrib.messages.middleware.MessageMiddleware` | 在强制改密之内：`process_view` 阶段消息框架已可用 |
| 12 | `django.middleware.clickjacking.XFrameOptionsMiddleware` | 最内层 |

两个由此而来的细节：`request.start` 与 `request.end` 各取一次用户名，所以**登录请求的 start 行记
`anonymous`、end 行记登录后的账号**；`ForcePasswordChangeMiddleware` 用 `process_view` 而不是
`__call__`，意味着**只有能解析到视图的地址才受它管**，且它在视图执行之前就返回 302。

### `/en/` 前缀怎么生效

1. `i18n_patterns` 包住的是 `/admin/` 之外的全部前台 include（`accounts`、`notices`、`content` 与 `/member/` 下各 app）。
2. 请求进来时 `LocaleMiddleware` 从地址前缀判定语言：`/` 是中文、`/en/` 是英文；没有 `/en/` 就用
   `LANGUAGE_CODE = "zh-hans"`。浏览器语言与 Cookie 都不参与。
3. 页面里的 `{% url %}` / `reverse()` 按**当前语言**自动加或去掉前缀，所以模板里不需要手写 `/en/`；
   顶栏的语言切换链接由 `core.templatetags.language_urls.language_url` 现算（`docs/development.md` §3.4）。
4. 中文是源语言：模板与代码里的 msgid 本身就是中文，英文译文在 `locale/en/LC_MESSAGES/django.po`。

### 启动时序

1. **导入 `config.settings`**：读环境变量 → `LOG_DIR.mkdir(parents=True, exist_ok=True)` 建出 `logs/`
   → 定义 `LOGGING` → **最后**才执行 `SECRET_KEY` 守卫。这些副作用都发生在模块导入期，所以
   「环境变量写错」以**进程起不来**的形式暴露；顺带一个可观察的细节：`DEBUG=False` 且密钥还是
   源码默认值时，进程是**在 `logs/` 已经建出来之后**才抛 `ImproperlyConfigured` 的。
2. **首次加载 `ROOT_URLCONF`**：`config/urls.py` 顶部的 `from config import admin` 顺手把后台标题与
   「身份管理」分组装上。URLconf 是惰性加载的，所以这发生在第一个请求（或第一次 `check`）时，不在启动那一刻。
3. 请求按上表穿过中间件链。

---

## 5. 错误处理与诊断

**启动即失败**（有意设计成「响的」）：

| 情形 | 形态 |
|---|---|
| `DEBUG=False` 且 `SECRET_KEY` 仍是源码默认串 | 导入期 `ImproperlyConfigured`（消息里带生成随机密钥的命令） |
| 整型环境变量填了非数字（如 `DJANGO_SECURE_HSTS_SECONDS=abc`） | 导入期 `ValueError`，且没有额外解释 |
| 数据库连不上／没 `source env.local.sh` | `manage.py` 任何命令都失败（数据库固定 PostgreSQL，没有回退） |
| `DEBUG=False` 没跑 `collectstatic` | 静态指纹（`ManifestStaticFilesStorage`）取不到 manifest，页面报错，见 `docs/deploy.md` §6 |

**上线门禁**：`deploy/deploy.sh` 在重启服务之前跑 `manage.py check --deploy --fail-level WARNING`，
CI 在 PR 上跑同一道门（`.github/workflows/ci.yml`）。它拦的是「不会让站点起不来、只会让它安静地不安全」
的退化——DEBUG 还开着、Cookie 没带 `Secure`、`SECRET_KEY` 还是源码默认值等；`SILENCED_SYSTEM_CHECKS`
的两条静音与开关绑定，所以那两个告警只在开关关着时被压住。**门禁不覆盖 `DJANGO_CSRF_TRUSTED_ORIGINS`**：
漏填要等成员提交表单才以 403 出现（`docs/deploy.md` §2.5 有实测记录），只能靠人对着 `env.template` 核。

**日志**（`logs/django.log`：`RotatingFileHandler`，10 MB × 5 份，UTF-8；同时输出终端）：

| logger | 级别 | 覆盖 |
|---|---|---|
| `django` / `django.request` / `django.server` | `INFO` / `ERROR` / `INFO` | 框架自身与开发服务器 |
| `accounts` / `notices` / `media` / `content` / `config` / `projects` / `competitions` / `reviews` / `equipment` / `discussion` / `core` | `DEBUG` | 各 app 与 config 包（`config.middleware` 的请求日志挂在 `config` 下） |

**每个自家包都要有自己的 logger**：`LOGGING["loggers"]` 里**逐个列出**（顺序同 `INSTALLED_APPS`，
`config` 夹在其中），配的都是一样的 `console` + `file` 两个 handler。漏掉一个的后果是静默的——它的生效
级别回落到 root 的 `WARNING` 且没有 handler，`logger.info(...)` 在级别检查处就被丢掉，终端与
`logs/django.log` 都不会出现；`logger.warning` 也只落到 Python 的 `logging.lastResort`（stderr），
**同样不进日志文件**。这与 `DEBUG` 取值无关（实测两种取值下生效级别都是 `WARNING`、handler 为空），
排查时会以为「什么都没发生」。`config/tests.py` 的 `AppLoggerTests` 盯着四个方向：**名单**（仓库里
实际有的包 vs 测试里那份显式清单，两头钉）、**配置节**、**运行时接线**、**真发一条 `INFO` 去文件里找**——
删掉哪一节、新增包忘了配、或把 `file` handler 的级别抬到 `ERROR`，都会红。

**诊断路径**：记下响应头 `X-Request-ID` → 在 `logs/django.log` 里搜这个 id → 看 `request.start` /
`request.end` 的状态与耗时 → 有 `request.exception` 就读紧随的 traceback（`docs/development.md` §7）。
请求日志只记 method／path／query／用户名／来源 IP／状态码／耗时，**不记口令、不记请求体、不记 Cookie**；
来源 IP 走 `core.audit.get_client_ip`，所以反代下它与审计、axes 是同一个口径。

---

## 6. 测试要点与已知限制

### 测试

| 文件 | 钉住什么 |
|---|---|
| `tests.py` 的 `RunningTestsDetectionTests` | `running_tests()` 认哪些命令行、不认哪些（`runserver`／`migrate`／`shell`／`gunicorn`），以及**判定与赋值之间没有断链**——测试进程里 `PASSWORD_HASHERS` 真的换成了 MD5。它守的是一道安全线：判定写坏会让生产静默落到弱哈希上，不会有任何报错 |
| `tests.py` 的 `SecurityHeadersTests` | 中间件真的挂在 `MIDDLEWARE` 里：CSP 是强制模式（不再带 `Report-Only`）、前台不含 `unsafe-inline`、`/admin/` 放宽但 `frame-ancestors`／`object-src` 照旧、`Permissions-Policy` 关掉摄像头等用不到的浏览器特性、视图自己发的头不被覆盖（`setdefault`） |
| `tests.py` 的 `AppLoggerTests` | 每个自家包都配了 logger 且**真的接上 `logs/django.log`**，四条：①仓库里实际的包（按安装位置现场数：在 `BASE_DIR` 之下、不在 site-packages 里）与测试里的显式清单**相等**——检测规则变哑或包增删了而清单没跟上，这条先红；②配置节在且 handlers 非空；③运行时生效级别不是 `WARNING`、挂着那个文件的 `RotatingFileHandler`；④每个包真发一条 `INFO`，再去文件里找它（前三条约是结构，这条是行为）。**加新包要同时改 `settings.LOGGING` 与清单** |

请求日志与强制改密这两个中间件的**行为**不在这里测：改密的拦截由 `accounts` 的用例覆盖
（首次登录强制改密、改密后解锁成员区），请求日志只有人工看 `logs/django.log`。

### 已知限制 / 当前不支持

- **logger 靠「显式列出」而不是兜底**：root 没有 handler，也没配 `root` 一节，所以没列进
  `LOGGING["loggers"]` 的 logger 一律收不到——第三方库（如 `axes`）的生效级别是 `WARNING` 且没有
  handler，它的 `debug` / `info` 在级别检查处**直接消失**，`warning` 及以上只经 `lastResort` 到
  stderr，**都不进 `logs/django.log`**（实测）。要用得单独加一节。
- **后台站点定制没有测试兜底**：`config/admin.py` 的标题与「身份管理」分组、以及它在 `config/urls.py`
  里的副作用导入，都没有断言盯着——改坏了唯一的发现方式是打开 `/admin/` 看首页。
- **「身份管理」分组只改首页索引**：各名册自己的 URL 与页面一个字都不动；单个 app 的索引页
  （`/admin/<app>/`）保持原样（`get_app_list(app_label=...)` 直接返回）。合成出来的分组不对应任何真实 app，
  没有 `/admin/roles/` 这个地址。
- **`ROSTER_MODELS` 的元组与 `core.roles` 的顺序要手动保持一致**：顺序即后台显示顺序（与各身份的
  `sort_order` 同源），漂了不会有报错。名册模型改名或搬家后忘记同步这一行，它会悄悄落回原 app 分组。
- **`running_tests()` 是整词匹配**：argv 里任何一项恰好等于 `test` 都会命中，不做子命令解析。这是它简单可靠的
  原因，也意味着带同名参数的其它入口会连带命中——它认与不认的清单由测试钉着。
- **ASGI 入口没有使用者**：仓库里有 `config/asgi.py`，但生产跑的是 `config.wsgi:application`（systemd + gunicorn）。
- **`RequestLoggingMiddleware` 里设的 `request._request_started_at` 目前没有别的读取点**：它是留给后续
  慢请求统计的钩子，删掉不会影响现有行为，但会改动 `request.start` 与 `request.end` 的耗时口径。
- **后台文案写死中文**：`site_header` / `site_title` / `index_title` 与 `ROLE_SECTION` 都是中文字面量，
  不进 `.po`——后台本来就不在双语范围内，**不要把这几处搬进 `gettext`**。
- **`check --deploy` 门禁的口径以 `deploy/deploy.sh` 为准**：它覆盖 DEBUG、Cookie、SECRET_KEY 等项，
  但覆盖不到 `CSRF_TRUSTED_ORIGINS`（见 §5）、也覆盖不到「成员实际访问的入口是否都写进白名单」。
