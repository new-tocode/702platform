# config 包

> 项目配置包：进程级装配——环境变量与设置、根路由、中间件链、后台站点定制、日志配置、
> WSGI／ASGI 入口。它管「整个进程以什么姿态运行」，**不管任何业务**：没有表、没有权限判定、
> 没有服务层，也不在 `INSTALLED_APPS` 里（所以它连 models 都没有）。

**什么时候看**：加或调环境变量、动中间件顺序与安全响应头、改根路由或双语前缀、
动 Cookie／HTTPS／HSTS／上传体积上限这类平台级开关、改日志分级、定制后台站点外观的时候。

---

## 1. 明确不做什么

| 不在这里 | 落在哪 |
|---|---|
| 任何表结构、业务判定与写操作 | **本包没有 `models.py` / `permissions.py` / `services.py`**，不在 `INSTALLED_APPS` 里 |
| 业务路由 | 各 app 的 `urls.py`；`config/urls.py` 只做 `include` 与命名空间 |
| 登录锁定的计数、冷却与判定 | django-axes；config 只给 `AXES_*` 阈值，并把两个回调指到 `core.audit.get_client_ip` 与 `accounts.axes.lockout_response` |
| 受保护件的存储与取件 | `core/storage.py` 与各 app 的取件视图；config 只定义两个媒体根 |
| 用户可见文案 | 模板与 `panels`（前台一律 `gettext`）。config 里只有后台标题，后台**不在双语范围** |
| 部署动作本身 | `deploy/*.sh`、systemd 与 Nginx 模板 |

## 2. 硬约定

改动时**不能破坏**的：

- **`AUTH_USER_MODEL = "accounts.User"` 不可中途更换**：所有业务表都以它为外键、迁移已按它建表，
  换它等于重建全库。加字段要在 `accounts` 里加，config 只负责指过去。
- **两个媒体根刻意分家**：`MEDIA_ROOT`（`mediafiles/`）公开、Nginx 直出；
  `PRIVATE_MEDIA_ROOT`（`protected_media/`）**刻意不在前者之下**。`config/urls.py` 在 `DEBUG=True` 时
  只挂 `MEDIA_ROOT`，受保护根本地也不挂——**「开发能直连、线上不能」这种差异会掩盖问题**。
  备份要同时收两个目录。
- **`/admin/` 不在双语名单里**：地址固定 `/admin/`，后台文案写中文原样、不进 `.po`。
  前台用 `i18n_patterns(prefix_default_language=False)`，**中文地址与改造前逐字节相同**；
  **地址即语言**，与浏览器语言、Cookie 都无关。
- **静音的检查项跟着开关走**：`SILENCED_SYSTEM_CHECKS` 由两个条件推导——`security.W004` 跟随
  `SECURE_HSTS_SECONDS`、`security.W008` 跟随 `SECURE_SSL_REDIRECT`。开关一打开，告警自动回来。
  **不要把它改成写死的清单**：一条永远为真的告警会让「有告警即失败」的上线门禁变成摆设。
- **两个「默认关」是刻意的**：`SECURE_SSL_REDIRECT` 与 `SECURE_HSTS_SECONDS` 默认关闭；HSTS 一旦生效，
  浏览器会在有效期内拒绝一切非 https 访问，证书出问题就锁死站点。
- **安全默认值站在安全那一侧**：`SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE` 默认开；
  `SESSION_COOKIE_AGE` 是 3 天且 `SESSION_EXPIRE_AT_BROWSER_CLOSE=True`——对装着实名信息与评审机密的站
  来说，这是取舍不是遗漏。
- **认证后端的顺序不能反**：`AxesStandaloneBackend` 在 `ModelBackend` 之前——先看这个账号／IP 是否已锁，
  锁着就直接拒绝，**正确的口令同样不放行**。反过来「锁定」就只是一句提示。
- **`AXES_RESET_ON_SUCCESS = False`**：成功登录只清该账号的失败计数，**不清 IP 那一格**；否则知道口令的人
  可以隔几次成功登一次把 IP 计数刷掉。锁定期间也不刷新计时（否则持续尝试能把合法用户永久关在门外）。
- **上传体积上限显式写死**：两个 memory size 都是 5 MB，不让它们随 Django 版本漂；视频能到几百 MB，
  靠的是文件上传走流式解析（超限落临时文件），整体上限另由 Nginx 的 `client_max_body_size` 与各 app
  的校验管。
- **前台 CSP 不含 `'unsafe-inline'`**：模板不写内联 `<script>`、不写行内样式，页面脚本放 `static/js/`；
  唯一放宽的是 `/admin/`（Django admin 模板自带内联脚本与样式，收不掉）。**今后每收紧一条 CSP 指令，
  都要在真实浏览器里把相关页面点一遍**——强制 CSP 拦错是静默的。
- **`django.contrib.postgres` 只为函数与查找**：无模型、无迁移，别把业务模型挂到它下面。
- **`DEFAULT_AUTO_FIELD = BigAutoField`**：主键一律数据库自增整数（地址里的 `<id>` 就是它）。
- **登录跳转三兄弟指向 accounts 的 URL 名**：改路由名时要同步；它们被 `@login_required` 与认证视图
  在框架层读取。
- **每个自家包都要有自己的 logger**：`LOGGING["loggers"]` 里**逐个列出**。漏掉一个的后果是静默的
  ——它的生效级别回落到 root 的 `WARNING` 且没有 handler，`logger.info(...)` 在级别检查处就被丢掉，
  终端与 `logs/django.log` 都不会出现。这与 `DEBUG` 取值无关，排查时会以为「什么都没发生」。

## 3. 已知限制 / 当前不支持

- **logger 靠「显式列出」而不是兜底**：root 没有 handler，也没配 `root` 一节，所以没列进
  `LOGGING["loggers"]` 的 logger 一律收不到——第三方库（如 `axes`）的 `debug` / `info` 直接消失，
  `warning` 及以上只经 `lastResort` 到 stderr，**都不进 `logs/django.log`**。要用得单独加一节。
- **后台站点定制没有测试兜底**：`config/admin.py` 的标题与「身份管理」分组、以及它在 `config/urls.py`
  里的副作用导入（**删掉那行 import ＝ 后台标题与分组静默回到默认，没有任何报错**），都没有断言盯着
  ——改坏了唯一的发现方式是打开 `/admin/` 看首页。
- **「身份管理」分组只改首页索引**：各名册自己的 URL 与页面一个字都不动；合成出来的分组不对应任何真实
  app，没有 `/admin/roles/` 这个地址。
- **`ROSTER_MODELS` 的元组与 `core.roles` 的顺序要手动保持一致**：顺序即后台显示顺序，漂了不会有报错。
  名册模型改名或搬家后忘记同步这一行，它会悄悄落回原 app 分组。
- **`running_tests()` 是整词匹配**：argv 里任何一项恰好等于 `test` 都会命中，不做子命令解析。
  这是它简单可靠的原因，也意味着带同名参数的其它入口会连带命中。**判定写坏（如只看 `sys.argv[1]`）
  ＝生产静默落到 MD5 哈希，没有任何报错**。
- **`env_bool` 不存在「值非法」这个报错**：设成 `0`／`false`／`off`／拼错的值一律是 `False`，
  写错了只会安静地按关闭处理。整型环境变量填非数字则是**导入期 `ValueError`，进程起不来**；
  `Path()` 不做 `resolve`，填相对路径时它相对**进程的工作目录**，不是项目根。
- **新增 app 有两种写错法**：漏了 `include` → URL 根本没注册（`reverse` 报 `NoReverseMatch`，
  一访问就炸）；**include 了但写在 `i18n_patterns` 之外** → 页面能开、`reverse` 也解析得动，
  只是没有 `/en/` 版——这一种不报错，只能靠 `/en/` 下点一遍发现。
- **`RequestLoggingMiddleware` 里设的 `request._request_started_at` 目前没有别的读取点**：
  它是留给后续慢请求统计的钩子，删掉不会影响现有行为，但会改动耗时口径。
- **后台文案写死中文**：`site_header` / `site_title` / `index_title` 与 `ROLE_SECTION` 都是中文字面量，
  不进 `.po`——后台本来就不在双语范围内，**不要把这几处搬进 `gettext`**。
- **ASGI 入口没有使用者**：仓库里有 `config/asgi.py`，但生产跑的是 `config.wsgi:application`。
- **上线门禁的口径以 `deploy/deploy.sh` 为准**：它覆盖 DEBUG、Cookie、SECRET_KEY 等项，但覆盖不到
  `CSRF_TRUSTED_ORIGINS`——那一项的漏填后果见
  [`../docs/更新维护/开发与部署.md`](../docs/更新维护/开发与部署.md) §4.3。
