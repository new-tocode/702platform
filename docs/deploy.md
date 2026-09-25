# 部署手册

单台 Linux 服务器部署。数据库固定 PostgreSQL（Django 5.2 要求 ≥14）。分两种形态：

- **快速验证**：`runserver` 直接跑起来看界面，适合一次性试跑。
- **生产部署**：`deploy/install.sh` 一步脚本，PostgreSQL + gunicorn + systemd + Nginx + HTTPS + 定时备份。

> 本地开发环境见 [`development.md`](development.md)；部署工件在 `deploy/`。

---

## 1. 快速验证（runserver）

服务器上需要 Python ≥3.10、PostgreSQL、git，以及一个可用的 PostgreSQL 角色/库。

```bash
git clone <仓库地址> /opt/702platform && cd /opt/702platform
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

# 配置数据库（必填；其余用默认）
export DJANGO_SECRET_KEY="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(50))')"
export DJANGO_DB_NAME=club702
export DJANGO_DB_USER=club702
export DJANGO_DB_PASSWORD='<数据库密码>'
export DJANGO_ALLOWED_HOSTS='服务器IP'

.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver 0.0.0.0:8000
```

- `DJANGO_ALLOWED_HOSTS` 写主机名或 IP，不带端口/协议，多个用逗号分隔。
- 云服务器需在安全组/防火墙放行 8000；断开 SSH 会中断服务，长期观察用 `tmux`/`screen`。
- 此形态 `DEBUG=1`，会把配置和堆栈暴露给访客，仅用于临时测试。

## 2. 生产部署（一步脚本）

`deploy/install.sh` 依次完成：**环境检测 → 配置检测 → 建库/建角色 → migrate → collectstatic → 建超管 → 注册 systemd 服务与备份 timer → 配置 Nginx → 健康检查**。

原则：**检测到依赖或配置不符合就中止**，绝不自动下载安装任何软件——缺什么、怎么补，提示都会写明。

### 2.1 前置：自行准备好依赖

```bash
sudo apt update
sudo apt install nginx postgresql python3 python3-venv python3-pip git gettext
sudo useradd -m -s /bin/bash club      # 运行应用与备份的系统用户，脚本要求它真实存在
```

### 2.2 获取代码并安装依赖

```bash
sudo mkdir -p /opt/702platform && sudo chown club:club /opt/702platform
sudo -iu club
cd /opt/702platform
git clone <仓库地址> .
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt -r requirements-prod.txt
```

### 2.3 配置 env.sh

```bash
cp deploy/env.template env.sh
chmod 600 env.sh
vi env.sh
```

**必须替换 `<尖括号>` 的项**：

| 配置项 | 示例 | 说明 |
|---|---|---|
| `DJANGO_SECRET_KEY` | `openssl rand -base64 36` 的输出 | 密钥，泄露需轮换 |
| `DJANGO_ALLOWED_HOSTS` | `club.example.com` | 不带协议/端口，逗号分隔 |
| `DJANGO_DB_NAME` / `DJANGO_DB_USER` | `club702` | 库名/角色（脚本自动创建） |
| `DJANGO_DB_PASSWORD` | 随机长串 | 数据库密码 |
| `DJANGO_SUPERUSER_USERNAME` / `_EMAIL` / `_PASSWORD` | `admin` / 邮箱 / 随机串 | 首次部署自动创建的超管 |
| `DEPLOY_SERVER_NAME` | `club.example.com` | Nginx `server_name` 与健康检查入口 |
| `DEPLOY_SYSTEM_USER` | `club` | 运行应用与备份的 Linux 系统用户 |

**有默认值、一般不改**：`DJANGO_APP_HOST/PORT`(`127.0.0.1`/`8000`)、`DJANGO_DB_HOST/PORT`(`127.0.0.1`/`5432`)、`DJANGO_BACKUP_SCHEDULE`(`daily`)、`DJANGO_BACKUP_RETAIN`(`14`)、`DJANGO_DEBUG`/Cookie/Proxy 项（安全默认，HTTPS 就绪后按需改）。

### 2.4 运行部署脚本

```bash
cd /opt/702platform
sudo ./deploy/install.sh
```

脚本会：校验无残留占位符 → 检测依赖（python/venv/各 Python 包/systemd/Nginx/PostgreSQL/gettext/备份日历表达式/部署用户，缺项则打印补法并中止）→ 幂等建角色与库 → `migrate` + `collectstatic` + `compilemessages` → 幂等建超管 → 注册并启动 `club702.service` 与 `club702-backup.{service,timer}` → 生成 Nginx 站点并 `nginx -t` + reload → 健康检查。

> 常见疑问：脚本不会自己下载安装；占位符没替换会逐个列出并中止；重复运行安全（建库/建超管幂等）；备份 timer 依赖本机 `pg_dump` 与媒体目录，单机形态下就在本机。

### 2.5 HTTPS

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d club.example.com
```

#### 现状：证书是借来的

本平台目前没有自己的域名备案与证书，线上 HTTPS 用的是**另一个已备案站点**的证书
（该站点与本平台无关）。这带来两个必须记住的后果：

- **HSTS 绝对不要开。** HSTS 一旦生效，浏览器会在有效期内拒绝一切非 https 访问，
  用户点「继续访问」也绕不过去。借用证书随时可能被收回，那时域名就被锁死了——
  只能换域名，或者让每个用户去清 HSTS 缓存。`DJANGO_SECURE_HSTS_SECONDS` 因此
  默认是 0，也不要手工去改。
- **不做整站跳 https。** 线上确实有人用 `http://IP` 直接访问；硬跳会把 IP 这条
  入口打到那个不属于本平台的域名上。`DJANGO_SECURE_SSL_REDIRECT` 默认关。

Cookie 的 Secure 标志反过来是**默认开**的：站点全程 https（IP 直连也一样），
所以给会话与 CSRF Cookie 加 Secure 不挡任何人，却能防住「登录后会话被同网段
明文取走」。`env.template` 里两项默认就是 1。

#### 拿到自己的证书之后

按这个顺序做，每步确认无误再走下一步：

1. 先只把证书挂上（`SSL_CERT_PATH` / `SSL_KEY_PATH`），确认 HTTPS 正常。
2. `env.sh` 里打开代理头与受信来源，重启：
   ```bash
   DJANGO_PROXY_SSL_HEADER=1
   DJANGO_CSRF_TRUSTED_ORIGINS=https://club.example.com
   ```
3. 确认全站没有 http 访问需求后，再开整站跳转：
   ```bash
   DJANGO_SECURE_SSL_REDIRECT=1
   ```
4. HSTS **最后**再考虑，且先给一个很短的窗口试水：
   ```bash
   DJANGO_SECURE_HSTS_SECONDS=60      # 先 60 秒，确认一周无事再逐步加长
   ```
   加长到 31536000（一年）之前，想清楚证书续期是不是自动的——证书一断，长窗口的
   HSTS 会让站点在整个窗口内都进不去。

上面 3、4 两步做的同时，`config/settings.py` 里的 `SILENCED_SYSTEM_CHECKS` 会
自动放回对应的 `security.W008` / `security.W004` 告警，`check --deploy` 随即重新
盯住它们——静音是跟着开关走的，不是写死的。

任何一步之后都可以跑：

```bash
.venv/bin/python manage.py check --deploy --fail-level WARNING
```

`deploy.sh` 在上线流程里已经内置了这一条：**任何告警都会让这次发布中止**，宁可不发，
也不让站点安静地退化。

### 2.6 上线自检

`curl -i http://127.0.0.1:8000/` 期望 200 且响应头含 `X-Request-ID`。再按业务流程走一遍：公开首页 → 管理员建成员账号 → 成员首次登录强制改密 → 内部通知按组可见 → 项目组/联系人竞赛报名 → 设备借还 → `/admin/core/auditlog/` 只读审计。

## 3. 更新与回滚

### 更新

```bash
# 开发机打 tag
git tag -a v1.0.1 -m "发布说明" && git push <remote> main --tags

# 服务器一条命令
cd /opt/702platform
sudo -u club bash -c './deploy/deploy.sh v1.0.1'   # club = DEPLOY_SYSTEM_USER
```

`deploy.sh` 自动：备份库与媒体（保留 RETAIN 份）→ checkout tag → 升级依赖 → **`check --deploy` 门禁** → `migrate` + `collectstatic` + `compilemessages` → 重启 → 健康检查。任何一步失败即中止，其中门禁那一步会拦下「DEBUG 还开着」「Cookie 没带 Secure」「SECRET_KEY 还是源码默认值」这类不会让站点起不来、只会让它安静地不安全的问题。版本号命名 `v主.次.修订`（修订=修复，次=新功能，主=不兼容）。

### 回滚

```bash
cd /opt/702platform
set -a; source env.sh; set +a
git checkout v1.0.0
.venv/bin/python manage.py migrate --noinput
systemctl restart club702
```

迁移本身出问题：停服后 `gunzip -c backups/db-<发布前>.sql.gz | PGPASSWORD=... psql -U $DJANGO_DB_USER $DJANGO_DB_NAME`（发布前那份备份在 RETAIN 份内不会被提前清掉）。

### 破坏性迁移纪律

删字段/删表/改类型**不要与依赖旧字段的功能同一次发布**：先加新列 + 双写，下次发布再删旧列。保证任意一版代码与当版数据库兼容，回滚才安全。

### 迁移删过模型时：清理陈旧权限项

删掉模型的迁移（如评审的 `0006` 把两张任务表并成 `ReviewTask`）不会顺带删掉 `django_content_type` 与 `auth_permission` 里指向旧模型的记录。发布后在服务器上跑一次：

```bash
.venv/bin/python manage.py remove_stale_contenttypes --noinput
```

`auth.Permission.content_type` 是 CASCADE（权限随之消失），`admin.LogEntry.content_type` 是 SET_NULL（后台操作历史保留、只是内容类型置空），所以这一步是安全的；不做的话，Admin 的权限列表里会出现指向已不存在模型的条目。

## 3.5 受保护上传件的目录迁移（一次性）

从「安全检查」那一版起，项目书、批注版、归档版、帖子图、头像、个人图册从
`mediafiles/` 搬到了 `protected_media/`。原因是前者由 Nginx 的 `/media/` 直出，
谁拿到路径谁就能取，而这几类文件的可见性由业务规则决定——视图里的权限判定因此
形同虚设。两个目录分开之后，`/media/` 只映射公开的媒体库配图。

**这次上线要按停机窗口做**，因为数据迁移 `core.0002_rehome_protected_uploads`
会**真实移动磁盘上的文件**：

```bash
# 1. 先备份（备份脚本已同时打包两个目录）
sudo -u club bash -c "cd /opt/702platform && source env.sh && ./deploy/backup.sh"

# 2. 停服，避免迁移期间有人正好在读文件
sudo systemctl stop club702

# 3. 部署（deploy.sh 会自动跑 migrate，其中就含这条搬运）
sudo -u club bash -c './deploy/deploy.sh v<新版本>'
```

迁移的特点：

* **幂等**：两个根的相对路径相同，搬完数据库里的字段值不用改；重跑只会发现目标
  已存在。中途失败可以原地重来。
* **不因缺文件而中止**：数据库里指向的文件若已不存在（运维挪过、备份不完整），
  只记一条 `private_media.missing` 警告并跳过，其余照搬。
* **可回滚**：反向迁移把文件搬回 `mediafiles/`。回滚代码的同时跑
  `manage.py migrate core 0001` 即可。

迁移跑完后，`protected_media/` 应当出现在应用目录下，且**不在** Nginx 的任何
`location` 里（配置里只映射 `mediafiles/`）。可以这样确认没有旁路：

```bash
# 取一个受保护文件的相对路径，拼成 /media/<路径> 请求，应当是 404
curl -s -o /dev/null -w '%{http_code}\n' https://<域名>/media/project_proposals/...
```

## 4. 备份与恢复

备份由 **`club702-backup.service`（oneshot）+ `club702-backup.timer`** 驱动，不用 cron：统一由 systemd 管理、`systemctl list-timers` 可查、`Persistent=true` 可补跑错过的备份。

```bash
# 频次 = env.sh 的 DJANGO_BACKUP_SCHEDULE（systemd OnCalendar 语法）
#   daily -> 每天 00:00 ; *-*-* 03:00:00 -> 每天 3 点
#   Mon..Fri *-*-* 02:00:00 -> 工作日 2 点 ; hourly ; *:0/30
systemctl list-timers | grep club702
systemctl status club702-backup.timer

# 手动备份
sudo -u club bash -c "cd /opt/702platform && source env.sh && ./deploy/backup.sh"

# 恢复数据库 / 媒体
gunzip -c backups/db-XXXX.sql.gz | PGPASSWORD=... psql -U club702 club702
tar -xzf backups/media-XXXX.tar.gz -C /opt/702platform
```

**媒体备份包含两个目录**：`mediafiles/`（媒体库配图，公开）与 `protected_media/`
（项目书、批注版、头像、图册，只经视图送出）。后者刻意不在前者之下，所以
`tar` 必须同时收两个；少一个会让受保护文件整批丢失，而数据库里的路径还指着它们。
`deploy/backup.sh` 与 `deploy/deploy.sh` 都已同时打包，自定义脚本时留意这一条。

保留份数由 `DJANGO_BACKUP_RETAIN` 控制（默认 14）；`backups/` 建议异地同步（脚本结尾留了 rsync 示意）。建议每季度做一次恢复演练。

> 备份里包含实名身份与全部评审意见，比在线库更集中。`backups/` 已随 `.gitignore`
> 排除在版本库外，权限也应只给部署用户；有条件的把异地副本加密。

## 5. 日常运维

| 事项 | 做法 |
|---|---|
| 应用日志 | `journalctl -u club702 -f`；应用内部日志 `logs/django.log` |
| 服务状态 | `systemctl status club702` |
| 证书续期 | certbot 自动（`systemctl list-timers | grep certbot` 验证） |
| 拨测 | 外部访问 `https://<域名>/` |
| 磁盘 | 关注 `mediafiles/`（视频单个 ≤500MB）、`backups/`、`logs/` |

## 6. 常见问题

| 现象 | 处理 |
|---|---|
| `DisallowedHost` | 把访问 IP/域名补进 `DJANGO_ALLOWED_HOSTS` 后重启（不带端口） |
| `DEBUG=0` 时页面无样式 | 忘记 `collectstatic`，或 Nginx 未映射 `/static/` |
| `DEBUG=0` 报 `Missing staticfiles manifest entry` | 生产启用了静态指纹，`collectstatic` 是硬要求；补跑 `collectstatic` 后重启 |
| `DEBUG=0` 时 `/media/` 404 | Nginx 未映射 `/media/` |
| 英文页面显示中文 | 界面英文的 `.mo` 未编译：服务器缺 `gettext`（`sudo apt install gettext`），或部署时跳过了 `compilemessages` |
| 上传视频 413 | Nginx `client_max_body_size` 太小（模板已设 520m） |
| `no such table` | 未 `migrate`，或数据库连接参数（`DJANGO_DB_NAME`/账号）有误 |
| 看不到内部通知 | 成员未完成首次改密，或不属于通知绑定的用户组 |
| `fe_sendauth: no password supplied` | 环境变量未加载：`source env.sh` 后再执行 |
| CSRF 验证失败（HTTPS 下） | 打开 `DJANGO_PROXY_SSL_HEADER` 与 `DJANGO_CSRF_TRUSTED_ORIGINS` |

**已知限制**：审计日志的来源 IP 取自 `REMOTE_ADDR`，经 Nginx 代理后统一记为 `127.0.0.1`；需要真实来源 IP 时须后续增加可信代理配置。
