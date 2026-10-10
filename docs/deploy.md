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
.venv/bin/python -m pip install --require-hashes -r requirements.txt

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
.venv/bin/python -m pip install --require-hashes -r requirements.txt -r requirements-prod.txt
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
| `DEPLOY_DOMAIN` / `DEPLOY_PUBLIC_IP` | `club.example.com` / `1.2.3.4` | Nginx `server_name`（两项都写上）与 `deploy.sh` 健康检查的 `Host` 头 |
| `DEPLOY_SYSTEM_USER` | `club` | 运行应用与备份的 Linux 系统用户 |

**有默认值、一般不改**：`DJANGO_APP_HOST/PORT`(`127.0.0.1`/`8000`)、`DJANGO_DB_HOST/PORT`(`127.0.0.1`/`5432`)、`DJANGO_BACKUP_SCHEDULE`(`daily`)、`DJANGO_BACKUP_RETAIN`(`14`)、`DJANGO_DEBUG`/Cookie/Proxy 项（安全默认，HTTPS 就绪后按需改）。
另有 `DJANGO_BACKUP_DIR`（备份落盘位置）与 `DJANGO_BACKUP_GPG_RECIPIENT`（备份加密），
见 4 节「备份位置与加密」。

### 2.4 运行部署脚本

```bash
cd /opt/702platform
sudo ./deploy/install.sh
```

脚本会：校验无残留占位符 → 检测依赖（python/venv/各 Python 包/systemd/Nginx/PostgreSQL/gettext/备份日历表达式/部署用户，缺项则打印补法并中止）→ 幂等建角色与库 → `migrate` + `collectstatic` + `compilemessages` → 幂等建超管 → 注册并启动 `club702.service` 与 `club702-backup.{service,timer}` → 生成 Nginx 站点并 `nginx -t` + reload → 健康检查。

> 常见疑问：脚本不会自己下载安装；占位符没替换会逐个列出并中止；重复运行安全（建库/建超管幂等）；备份 timer 依赖本机 `pg_dump` 与媒体目录，单机形态下就在本机。
>
> 升级到带「文件指纹」的版本时，`migrate` 会顺带读一遍盘上的上传件，把已有文件的 SHA-256 补进记录（几百个文件几秒钟），**不需要额外跑任何命令**。若日志里出现 `file_digest.backfill.missing`，说明那条记录指着文件而盘上没有——迁移会跳过它继续，但那是数据不完整，值得查一下。
>
> 升级到带「历年获奖判重」的版本时，`migrate` 会执行 `CREATE EXTENSION pg_trgm`（`content.0004_pg_trgm`）。pg_trgm 是 **contrib 扩展，不随 PostgreSQL server 包一起装**：PGDG 的 RPM 把它放在 `postgresql<主版本>-contrib` 里（如 `postgresql16-contrib`），Debian 系在 `postgresql-contrib` 里。只装了 server 的机器会报 `extension "pg_trgm" is not available`（`Could not open extension control file ".../pg_trgm.control"`）——装包即可，不需要重启 PostgreSQL：
>
> ```bash
> sudo dnf install -y postgresql16-contrib     # RHEL 系（PGDG）；按实际主版本改包名
> sudo apt install postgresql-contrib          # Debian / Ubuntu
> ```
>
> `deploy/deploy.sh` 与 `deploy/install.sh` 在 `migrate` 前会先探一次扩展可用性，缺了就直接给出上面这两条命令再退出，不会再抛一大段 traceback。扩展在位时不会因权限失败：它自 PostgreSQL 13 起是 trusted 扩展，**库的属主就能创建**，而 `install.sh` 正是以应用角色为属主建的库（`createdb -O "$DJANGO_DB_USER"`）。真遇到权限被收走的库，用超级用户执行一次下面这条再重跑 `migrate` 即可：
>
> ```bash
> sudo -u postgres psql -d "$DJANGO_DB_NAME" -c 'CREATE EXTENSION IF NOT EXISTS pg_trgm;'
> ```

### 2.5 HTTPS

证书走 Let's Encrypt 的 **IP 地址证书**（2026-01 起签发，不需要域名、也不需要备案），
由独立 venv 里的 certbot 签发与续期。签发命令见 `deploy/env.template` 里
`SSL_CERT_PATH` 上方的注释；`install.sh` 发现还没签证书时，会把同一条打出来。

#### 相关事实（2026-09-25 实地核对）

生产实测（实例 `<实例ID>`，用户 `<部署用户>`）：

| 项 | 实际值 |
|---|---|
| 应用目录 | `/home/<部署用户>/applications/702platform` |
| Nginx 站点配置 | `/etc/nginx/conf.d/club702.conf`（Alibaba Cloud Linux 3，conf.d 布局） |
| `server_name` | `<域名> <公网IP>` |
| `ssl_certificate` | `/etc/letsencrypt/live/<公网IP>/fullchain.pem`（本平台自己的 IP 证书；2026-10-05 之前是别家域名的，那一行已按现状更新） |
| 监听 | 80 与 443 **都在提供完整服务**（80 不是跳转） |
| 成员访问 | 全走 `https://<IP>`；经确认**没有人用 http** |

#### 证书与续期

| 项 | 值 |
|---|---|
| 证书 | IP 地址证书，走 shortlived profile——**只有几天有效期**，不是 90 天 |
| 续期单元 | `club702-certbot-renew.timer`，一天两次。短周期证书下这是硬需求而不是奢侈：certbot 在剩余不足寿命 1/3（几天寿命即约 2 天）时才动手续，一天两次意味着到期前有 4 次左右尝试机会，单次抖动不至于把证书放过期 |
| certbot | `env.sh` 的 `CERTBOT_BIN`（`/opt/certbot/bin/certbot`）；`install.sh` 用它渲染续期单元，并要求 ≥ 5.4（`--ip-address` 是 5.3 引入的，webroot 方式要 5.4） |
| 验收 | `systemctl list-timers club702-certbot-renew.timer --all`、`sudo /opt/certbot/bin/certbot renew --dry-run` |

**手动碰证书时最容易踩的坑：这台机器上有两个 certbot。** 发行版仓库那个
（`/usr/bin/certbot`，Alibaba Cloud Linux 3 是 1.22）认不出 IP 证书，`renew` 会报：

```
Failed to renew certificate <公网IP> with error: At least one of domains or ipaddrs parameter need to be not empty
```

**这是假故障**——它解析出的标识符列表是空的，而真正负责续期的那个（`CERTBOT_BIN`，≥ 5.4）
一切正常。分辨方法：输出里 `Simulating renewal of an existing certificate for` 后面**空着**
就是跑错了二进制，对的版本会把那个 IP 打印出来。所以这类命令一律写全路径。另有两条容易误读的
输出：到 `acme-staging-v02.api.letsencrypt.org` 的 `ReadTimeout` 是网络抖动（`--dry-run` 走
staging），重试即可；`certbot reconfigure` 说 `No changes were made to the renewal
configuration.` 是「配置已经就是这样」——它是在 staging 试续**成功之后**才说这句，不是失败。

#### 当年：证书是借来的（2026-09-25；2026-10-05 已换成本平台自己的 IP 证书）

当时站点跑在一张别家域名的证书上，由此定下三条结论。现在这样读：

- **HSTS 保持 0**，但理由换了：证书现在就是本平台自己的，问题不再是「域名不匹配」，
  而是短周期证书只有几天寿命——续期连续失败几天，长窗口的 HSTS 就会把成员锁在门外，
  且用户无法绕过。要开见末尾「拿到自己的证书之后」第 4 步，先给 60 秒。
- **整站跳 https 仍没做**：这已经是需求问题而不是证书问题（成员本来就全走 https）。
  要做见同一条的第 3 步；**动手前先确认 `server_name`**——IP 证书覆盖不了域名，
  站点若还留着一个域名入口，硬跳会把它跳到一张不匹配的证书上。
- **Cookie 的 `Secure` 要显式打开**，这条与证书无关，见下一节的 env.sh 四项。

关于最后一条，有个容易搞错的地方值得写清楚：`SESSION_COOKIE_SECURE` 是**直接决定**
Cookie 上带不带 `Secure` 属性的（Django 里就是 `secure=settings.SESSION_COOKIE_SECURE`），
与 `DJANGO_PROXY_SSL_HEADER` **无关**。代理头管的是另一件事——让 Django 知道
「这个请求其实是 https」，影响 `request.is_secure()`、CSRF 的 Origin 校验、
以及 `SECURE_SSL_REDIRECT` 会不会误判成死循环。

#### 升级到本版本时要改的 env.sh（四项，缺一不可）

新版本里这几项的代码默认值虽然已经调过，但**生产 `env.sh` 里是显式写死的，会覆盖
代码默认值**——所以要生效必须改 `env.sh`：

```bash
# 会话与 CSRF Cookie 只走 https（成员全走 https，不会挡住任何人）
DJANGO_SESSION_COOKIE_SECURE=1
DJANGO_CSRF_COOKIE_SECURE=1
# 让 Django 认得 Nginx 发来的 X-Forwarded-Proto
DJANGO_PROXY_SSL_HEADER=1
# 受信来源：成员实际访问的**每个**入口都要写，含协议
DJANGO_CSRF_TRUSTED_ORIGINS=https://<域名>,https://<公网IP>
```

前三项改完才能通过 `deploy.sh` 的 `check --deploy` 门禁，否则它以 `security.W012` /
`W016` 中止部署（有意设计：宁可发布失败，也不让站点安静地不安全）。
`DJANGO_SECURE_SSL_REDIRECT` 与 `DJANGO_SECURE_HSTS_SECONDS` **继续留空或 0**，理由见上。

**第四项 `DJANGO_CSRF_TRUSTED_ORIGINS` 不是可选项，漏填的后果是表单提交 403。**
这一条在 2026-09-26 的生产上实测确认过。Django 每次 POST 都会把浏览器发来的
`Origin` 头与「`request.is_secure()` 判断出的协议 + Host」比对，对不上就拒绝：

```
Forbidden (Origin checking failed - https://<公网IP> does not match any trusted origins.)
```

生产上 TLS 由 Nginx 终结、Django 自己看不出是 https（除非开 `PROXY_SSL_HEADER`），
于是它期望 `http://…` 而浏览器发的是 `https://…`，必然对不上。生产日志里为此积累过
140 次 `Referer checking failed - no Referer` 与 34 次
`Referer is insecure while host is secure`——都是同一个根因的不同表现。

**为什么以前「看起来能用」**：不带 `Origin` 头的 POST 在 `is_secure()=False` 时不做
校验，就侥幸过了；带 `Origin` 头的现代浏览器请求会被拒。所以这是「偶发提交失败」的
来源，不是一直坏。

四个开关的实测组合（`https://<IP>` 入口、Nginx 发 `X-Forwarded-Proto: https`）：

| 配置 | `is_secure()` | Origin 校验 |
|---|---|---|
| 现状（`PROXY=0`、`TRUSTED` 空） | False | **拒绝** |
| 只改 `PROXY_SSL_HEADER=1` | True | 通过，但会**追加** Referer 校验（Django 对 HTTPS 的额外保护） |
| 只加 `TRUSTED_ORIGINS` | False | **仍拒绝**（`is_secure()` 没变） |
| **两个都设** | True | **通过** ← 正确组合 |

所以 `PROXY_SSL_HEADER` 与 `CSRF_TRUSTED_ORIGINS` 要一起设：前者让 Django 知道
自己在 https 下，后者给出白名单。`server_name` 含域名与 IP 两项，两个入口都要写进
`CSRF_TRUSTED_ORIGINS`。

#### 拿到自己的证书之后

1. 先只把证书换成本平台自己的（`SSL_CERT_PATH` / `SSL_KEY_PATH`），确认 HTTPS 正常。
2. `env.sh` 里加受信来源（写成员实际访问的那个入口，IP 证书就是 `https://<公网IP>`；
   站点若还有域名入口，把域名那条也写上）：
   ```bash
   DJANGO_CSRF_TRUSTED_ORIGINS=https://<公网IP>
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

上面 1、3、4 步做的同时，`config/settings.py` 里的 `SILENCED_SYSTEM_CHECKS` 会
自动放回对应的 `security.W008` / `security.W004` 告警，`check --deploy` 随即重新
盯住它们——静音是跟着开关走的，不是写死的。

### 2.6 上线自检

`deploy.sh` 的收尾健康检查**先打 Nginx、打不通再退回直连 gunicorn**，通过后会打印这次
验到了哪一层（`经 Nginx（Host: … → 127.0.0.1:80）` 或 `直连 gunicorn（…，未经 Nginx）`）。
**两种结果的含义不同**：成员走的是 Nginx 这条路，只验到直连等于**没验到成员看到的那一层**
——Django 确实活着，但 Nginx 与它的转发可能是坏的。早先的版本只打直连，于是「成员看到 502、
部署报成功」是可能的。所以看到「直连」就要去查 Nginx（`nginx -t`、`systemctl status nginx`、
`journalctl -u nginx -n 50`），别把它当成绿灯。

两条路手工复核：

```bash
curl -i -H 'Host: <DEPLOY_DOMAIN>' http://127.0.0.1:80/   # 经本机 Nginx；Nginx 不在本机时换成真实入口
curl -i http://127.0.0.1:8000/                            # 直连，期望 200 且响应头含 X-Request-ID
```

再按业务流程走一遍：公开首页 → 管理员建成员账号 → 成员首次登录强制改密 → 内部通知按组可见 → 项目组/联系人竞赛报名 → 设备借还 → `/admin/core/auditlog/` 只读审计。

### 2.7 配置的优先级与「生效值」

本项目**没有配置文件层，也没有命令行开关**——一切配置只有两个来源，后者覆盖前者：

1. **代码默认值**：`config/settings.py` 里 `os.environ.get("DJANGO_…", <默认>)` 的第二个参数。
2. **环境变量**：本地是 `env.local.sh`，生产是 `env.sh`（systemd 单元用 `EnvironmentFile` 读它）。

所以「改了代码默认值却不生效」几乎总是因为 **`env.sh` 里显式写着旧值**——它优先。改动安全开关（Cookie、HSTS、SSL 跳转）时特别容易踩：代码默认值调了，线上文件里的那一行还在。

看当前生效值（不打印密钥）：

```bash
set -a; source env.sh; set +a
.venv/bin/python -c "import os
for k in ('DJANGO_DEBUG','DJANGO_ALLOWED_HOSTS','DJANGO_SESSION_COOKIE_SECURE','DJANGO_CSRF_COOKIE_SECURE','DJANGO_PROXY_SSL_HEADER','DJANGO_SECURE_SSL_REDIRECT','DJANGO_SECURE_HSTS_SECONDS','DJANGO_CSRF_TRUSTED_ORIGINS','DJANGO_BACKUP_DIR','DJANGO_BACKUP_SCHEDULE'):
    print(f'{k}={os.environ.get(k, \"(未设，用代码默认值)\")}')"
```

> `install.sh` 与 `deploy.sh` 里那些占位符校验（`<尖括号>`）就是防「复制模板后忘了替换」——它是硬门禁，不会放行。

## 3. 更新与回滚

### 更新

```bash
# 开发机打 tag
git tag -a v1.0.1 -m "发布说明" && git push <remote> main --tags

# 服务器一条命令（<部署用户> = env.sh 里的 DEPLOY_SYSTEM_USER）
cd ~/applications/702platform
./deploy/deploy.sh v1.0.1
```

> 本平台的生产路径是 `/home/<部署用户>/applications/702platform`，部署用户是
> `<部署用户>`；`docs` 别处出现的 `/opt/702platform`、`club` 是模板默认值。

### 升级到「安全检查」那一版的完整步骤

这一版有几处**必须先改 `env.sh` 才能通过上线门禁**，顺序不能颠倒：

```bash
cd ~/applications/702platform

# 1) 先改 env.sh 的四项（理由与取值见 2.5 节；第四项漏填会导致表单提交 403）
#    DJANGO_SESSION_COOKIE_SECURE=1
#    DJANGO_CSRF_COOKIE_SECURE=1
#    DJANGO_PROXY_SSL_HEADER=1
#    DJANGO_CSRF_TRUSTED_ORIGINS=https://<域名>,https://<公网IP>
#    （chmod 600 由 deploy.sh 自己会做，手工改完顺手执行一次也无妨）
vi env.sh

# 2) 跑部署（它会：备份 → 切版本 → 装依赖 → check --deploy 门禁 → 迁移 →
#    静态文件 → 编译翻译 → 重启 → 健康检查（先打 Nginx、再退回直连 gunicorn）；
#    任何一步失败即中止）
./deploy/deploy.sh v<新版本>

# 3) 起来之后确认三件事
curl -sI https://127.0.0.1/ -k | grep -i set-cookie     # 登录后应当带 Secure
systemctl is-active club702 club702-backup.timer
ls -d protected_media                                   # 迁移建出来的受保护目录
```

这一版里**不需要停机**：那条会移动文件的数据迁移在生产数据上是空操作（见 3.5 节）。

如果第 1 步的前三项忘了改，第 2 步会停在门禁那一步、以 `security.W012`/`W016` 报错
退出——迁移都还没跑，服务也还是旧版在跑，**不会造成任何破坏**。补上再跑一次即可。

但**第四项（`CSRF_TRUSTED_ORIGINS`）漏填不会被门禁拦下**：它不是 `check --deploy`
的检查项，症状要等成员提交表单时才出现（403，见 2.5 节的实测）。所以这一项请照着
模板逐字确认，别凭印象。

`deploy.sh` 自动：备份库与媒体（保留 RETAIN 份）→ **`chmod 600 env.sh`** → checkout tag → 升级依赖 → **`check --deploy` 门禁** → `mkdir -p protected_media` → `migrate` + `collectstatic` + `compilemessages` → 重启 → 健康检查（先打 Nginx、再退回直连 gunicorn，详见 2.6）。任何一步失败即中止，其中门禁那一步会拦下「DEBUG 还开着」「Cookie 没带 Secure」「SECRET_KEY 还是源码默认值」这类不会让站点起不来、只会让它安静地不安全的问题。版本号命名 `v主.次.修订`（修订=修复，次=新功能，主=不兼容）。

### 回滚

健康检查失败时 `deploy.sh` 会把这套步骤直接打印出来。**回滚不能靠重跑 `deploy.sh`**：
它第一步是备份（无害但会多留一份）、第五步却是**正向** `migrate`，方向与回滚相反——
用新代码的迁移去回滚旧代码，只会把事情弄得更糟。

```bash
cd ~/applications/702platform
set -a; source env.sh; set +a
git checkout v1.0.0
.venv/bin/python manage.py migrate --noinput   # 仅当这一版带了迁移；反向迁移在旧 tag 的代码里
systemctl restart club702
```

> 注意 `env.sh` 与 `backups/` 都在 `.gitignore` 里，`git checkout` 不会动它们——回滚
> **不会**把配置和备份一起退回去（这正是想要的：配置里有前一次发布补上的项，退回去反而
> 可能过不了旧版门禁）。但如果这次发布**改了 `env.sh` 里的必需项**（如
> `DJANGO_CSRF_TRUSTED_ORIGINS`），旧版本代码不会因此出问题，无需回退配置。

数据库也要退回时，用**发布前**那份备份手工恢复（它在 `RETAIN` 份内不会被提前清掉）：

```bash
systemctl stop club702
gunzip -c "$BACKUP_DIR/db-<发布前那份>.sql.gz" | PGPASSWORD="$DJANGO_DB_PASSWORD" \
    psql -U "$DJANGO_DB_USER" -h "${DJANGO_DB_HOST:-127.0.0.1}" "$DJANGO_DB_NAME"
systemctl start club702
```

恢复会覆盖当前数据，**确认过再执行**。

### 破坏性迁移纪律

删字段/删表/改类型**不要与依赖旧字段的功能同一次发布**：先加新列 + 双写，下次发布再删旧列。保证任意一版代码与当版数据库兼容，回滚才安全。

### 迁移删过模型时：清理陈旧权限项

删掉模型的迁移（如评审的 `0006` 把两张任务表并成 `ReviewTask`）不会顺带删掉 `django_content_type` 与 `auth_permission` 里指向旧模型的记录。发布后在服务器上跑一次：

```bash
.venv/bin/python manage.py remove_stale_contenttypes --noinput
```

`auth.Permission.content_type` 是 CASCADE（权限随之消失），`admin.LogEntry.content_type` 是 SET_NULL（后台操作历史保留、只是内容类型置空），所以这一步是安全的；不做的话，Admin 的权限列表里会出现指向已不存在模型的条目。

## 3.5 受保护上传件的目录迁移（一次性）

从本版本起，项目书、批注版、归档版、帖子图、头像、个人图册从 `mediafiles/` 搬到了
`protected_media/`。原因是前者由 Nginx 的 `/media/` 直出，谁拿到路径谁就能取，而这
几类文件的可见性由业务规则决定——视图里的权限判定因此形同虚设。两个目录分开之后，
`/media/` 只映射公开的媒体库配图。

迁移 `core.0002_rehome_protected_uploads` 会真实移动磁盘上的文件，所以理论上要停机。
**但本平台的实际数据让这条迁移是空操作**（2026-09-25 实地核对）：

```sql
profiles_with_avatar=0   gallery_images=0   group_proposals=0
post_images=0            review_tasks_with_file=0   archived=0
```

六类受保护文件的记录数**全部为 0**，`mediafiles/` 下只有 `uploads/`（2 张公开队刊
图）。所以没有文件可搬，迁移跑一遍什么都不做，立刻结束。**这次上线不需要停机窗口。**

往后（有成员真正用过这些功能时）再遇到这条迁移，才需要按停机来做：

```bash
# 1. 先备份
cd ~/applications/702platform && ./deploy/backup.sh

# 2. 停服，避免迁移期间有人正好在读文件
sudo systemctl stop club702

# 3. 部署（deploy.sh 会自动跑 migrate，其中就含这条搬运）
./deploy/deploy.sh v<新版本>
```

迁移的特点：

* **幂等**：两个根的相对路径相同，搬完数据库里的字段值不用改；重跑只会发现目标
  已存在。中途失败可以原地重来。
* **不因缺文件而中止**：数据库里指向的文件若已不存在（运维挪过、备份不完整），
  只记一条 `private_media.missing` 警告并跳过，其余照搬。
* **可回滚**：反向迁移把文件搬回 `mediafiles/`。回滚代码的同时跑
  `manage.py migrate core 0001` 即可。

迁移跑完后，`protected_media/` 会出现在应用目录下，且**不在** Nginx 的任何
`location` 里（配置只映射 `mediafiles/`）。可以这样确认没有旁路：

```bash
# /media/ 只该指到 mediafiles/；把受保护文件的相对路径拼进去应当取不到
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

保留份数由 `DJANGO_BACKUP_RETAIN` 控制（默认 14）。

### 备份位置与加密

备份默认落在 **`/var/backups/club702`**（`DJANGO_BACKUP_DIR` 可改），**不在应用目录
里**。

**这一条防的是什么，要说清楚**：systemd 给了应用进程整个应用目录的写权限
（`club702.service` 的 `ReadWritePaths=APP_DIR`，配合 `ProtectSystem=full`）。备份
留在应用目录里，意味着**一旦 Web 应用被攻陷，攻击者能删改备份**——而备份的意义正是
「数据被改了还能回到从前」。外置目录不在那个可写范围里，应用进程碰不到它。

**它防不住什么**：拿到部署用户 Shell 的人（SSH 登录、或被提权到该账号的攻击者）
照样能 `rm -rf` 那个目录，因为属主就是它。要防这种情况只能靠**异地副本**（见下）。
所以三件事的优先级是：**异地副本 > 移出应用目录 > 加密**。

**目录怎么建**：`/var` 属 root，日常部署（`deploy.sh`）不提权、建不出来，所以由
`install.sh`（有 sudo）负责一次性创建并 `chown` 给部署用户。`backup.sh` 每次运行会
自己把权限收紧到 `700`（目录）与 `600`（文件）——实测过旧备份是 `644`、目录 `755`，
同机任何账号都能读走。若目录创建失败，脚本会打印需要执行的三条 `sudo` 命令。

> `backup.sh` 自己的兜底值是**应用目录内**，与这里的推荐值不同，这是有意的：它由
> systemd timer 每天自动跑，兜底值指向一个尚未创建的外置目录会让**备份直接失败**
> （比备份在应用内更糟）。新部署由 `install.sh` 建目录、`env.template` 写路径；
> 老部署不受升级影响。

**加密**：在 `env.sh` 里填 `DJANGO_BACKUP_GPG_RECIPIENT`（gpg 公钥的收件人标识），
备份就会加密后落盘；不填则明文保存，脚本每次都会打印提醒。备份里是实名身份、学号
手机号与全部评审意见，比在线库更集中，值得加密：

```bash
# 在备份机或你自己的机器上生成密钥对，把公钥导入服务器
gpg --full-generate-key                       # 生成（私钥保管好，恢复时要用）
gpg --export --armor <邮箱> > backup-pub.asc  # 导出公钥
# 服务器上导入，然后 env.sh 里填 DJANGO_BACKUP_GPG_RECIPIENT=<邮箱>
sudo -u club gpg --import backup-pub.asc
```

恢复加密备份：`gpg --decrypt db-XXXX.sql.gz.gpg | gunzip | psql ...`。

**异地**：本机备份挡不住主机级故障（磁盘损坏、误删、勒索），异地那份才是最后一道。
脚本结尾留了 rsync 示意，把它接进定时任务即可。

**取回本地**（手动备份一份到自己的机器）：下载**时间戳相同**的一对文件——它们是分两步
导出的，只取其一会出现「库里有记录、文件没了」。

```bash
# 带外置目录时，先把最近的一对名字取出来
ssh <部署用户>@<服务器> 'ls -1t /var/backups/club702/db-*.sql.gz | head -1; \
                         ls -1t /var/backups/club702/media-*.tar.gz | head -1'

# 无公网 IP 的实例用 workbench CLI（单文件上限 1GB）
STAMP=2026-09-26-0934
workbench download /var/backups/club702/db-$STAMP.sql.gz    ./backup-db-$STAMP.sql.gz \
  --instance-id <实例ID> --port <SSH端口> --user-name <部署用户>
workbench download /var/backups/club702/media-$STAMP.tar.gz ./backup-media-$STAMP.tar.gz \
  --instance-id <实例ID> --port <SSH端口> --user-name <部署用户>
```

取回后**在本地加密或放进加密盘**：`db-*.sql.gz` 里有成员姓名、学号手机号、密码散列
与全部评审意见，是你电脑上最敏感的文件之一。

恢复：
```bash
gunzip -c backup-db-<时间戳>.sql.gz | PGPASSWORD=... psql -U <用户> <库名>
tar -xzf backup-media-<时间戳>.tar.gz -C <应用目录>
```

**一致性**：数据库与媒体是分两步导出的，不是同一时间点的快照，恢复后可能出现
「库里有记录、媒体文件缺失」。社团规模下这个窗口是秒级，可以接受；要严格一致就先
停写。数据库与媒体用同一份时间戳命名，配对恢复即可。

> `backups/`（旧位置）已随 `.gitignore` 排除在版本库外。

### 恢复演练（每季度一次，别只在出事时做）

没验证过的备份不算备份。演练的目标是**在另一处**把备份变成能跑的服务，而不是「看着文件在」：

1. 取回一对**时间戳相同**的 `db-*.sql.gz` 与 `media-*.tar.gz`（见上一节）。
2. 在一台临时机器上装好 PostgreSQL 与 Python 环境，**用与生产相同的 `DJANGO_DB_*` 名字**建库。
3. 恢复库与两个媒体目录，`manage.py migrate --check` 应当没有任何待应用的迁移。
4. 起 `runserver`，确认三件事：能登录、**受保护件能下载**（项目书/头像）、公开页的图能显示（`/media/`）。
5. 记下这次演练的日期、备份时间戳与结果（一行即可）——**这份记录本身就是审计证据**：

   | 日期 | 备份时间戳 | 结果 |
   |---|---|---|
   | （尚未做过） | | |

> 加密过的备份要先解密：`gpg --decrypt db-*.sql.gz.gpg | gunzip | psql …`；忘了私钥等于没有备份，私钥要留在备份机而不是生产机上。

## 5. 日常运维

| 事项 | 做法 |
|---|---|
| 应用日志 | `journalctl -u club702 -f`；应用内部日志 `logs/django.log` |
| 服务状态 | `systemctl status club702` |
| 证书续期 | `club702-certbot-renew.timer` 一天两次；验证用 `systemctl list-timers club702-certbot-renew.timer --all` 与 `sudo /opt/certbot/bin/certbot renew --dry-run`（**必须写全路径**——PATH 里的 `certbot` 是发行版的旧版，会给一个查不出所以然的假故障） |
| 拨测 | 外部访问 `https://<域名>/` |
| 磁盘 | 关注 `mediafiles/`（视频单个 ≤500MB）、`backups/`、`logs/` |

### 5.1 容量与扩展

单台服务器、单进程 gunicorn、数据库在本机——社团规模下够用，但有几处会先满：

| 会先满的 | 现状 | 满了怎么办 |
|---|---|---|
| **磁盘** | 媒体文件（视频单个 ≤500 MB）、`logs/`（10 MB × 5 轮转）、备份（默认留 14 份，含媒体包） | 先看 `du -sh mediafiles protected_media logs`；媒体是增长主项，可把 `DJANGO_BACKUP_RETAIN` 调小或把备份挪到更大的盘 |
| **上传体积** | Nginx `client_max_body_size 520m`（要给视频留余量），Django 侧另有各自的类型上限 | 改 Nginx 模板要「先 `deploy.sh` 再 `install.sh`」，并读回 `/etc` 下的文件核对 |
| **并发** | gunicorn 同步 worker；页面脚本极少，整页表单提交为主 | 加 worker 数（`club702.service` 的 `--workers`）；真到瓶颈先量再改 |
| **数据库** | 单库、无只读副本；最大的表是审计日志与站内消息 | 审计日志可按年份归档，但**清理要先走 §5.3 的逃生口**（只追加是数据库在守）；消息表有按来源的级联清理 |
| **媒体文件数** | 公开件按 `uploads/%Y/%m/` 分目录，受保护件按类型 + `%Y/%m/` 分 | 单目录几十万文件才需要再分片 |

要换形态（对象存储、视频转码、多机）时，媒体这一层是刻意留好的接缝：所有引用走 `MediaFile`，切 `django-storages` 只改存储配置一处（见 [`media/README.md`](../media/README.md)）。

### 5.2 废弃与退役

- **旧版本**：服务器上的代码**只从 git tag 取**（`deploy.sh` 强制），任意历史 tag 都能 `git checkout` 回去；数据库侧靠「破坏性迁移纪律」保证任一版代码与当版库兼容。不再维护的旧 tag 留在仓库里，不做单独的支持承诺。
- **证书与域名**：换证书只改 `env.sh` 的两个路径 + `install.sh` 重渲染续期单元；**退役某个入口**（域名或 IP）要从 `nginx` 模板的 `server_name` 与 `DJANGO_CSRF_TRUSTED_ORIGINS` 里同时去掉，否则表单提交会因 Origin 校验失败。
- **整站下线**顺序：① 公告通知成员 → ② 停 `club702.service`（站点不再可用）→ ③ 最后备份一次库与**两个**媒体目录 → ④ 把备份取回本地并确认可读 → ⑤ 再决定何时删除服务器上的数据与 Let's Encrypt 的续期单元。
- **成员数据**：备份里有实名身份、学号手机号与全部评审意见。退役时按所在组织的留存要求处理——**先备份、后删除，且别把备份留在即将释放的机器上**。

### 5.3 审计日志：改不动是数据库在守，以及它的逃生口

审计表 `core_auditlog` 上挂着行级触发器 `core_auditlog_append_only`（迁移 `core.0003`）：任何 `UPDATE` / `DELETE` 命中即 `RAISE EXCEPTION`，语句回滚，应用侧看到 `DatabaseError`。这是**有意挡住正常路径的**——数据修复脚本、`queryset.update()`、数据库客户端都改不动留痕，别看到报错就去把它摘掉。

两个真实的副作用，先知道再遇到：

- **删账号会被挡**：`AuditLog.user` 是 `SET_NULL`，删用户前要先把他名下的审计行置空（一次 `UPDATE`）→ **有审计行的账号删不掉**，一条都没有的账号照常删得掉。账号退场的正常口径是**停用**（后台取消 `is_active`），不是删除。
- **归档审计日志**（按年份清理旧行）也不能直接 `DELETE`，得走下面的逃生口。

**逃生口**（两条，都不改代码、不改迁移）：

```sql
-- 甲：临时摘掉触发器（要表属主，即应用账号；只影响这一张表）
ALTER TABLE core_auditlog DISABLE TRIGGER core_auditlog_append_only;
--   ……做完要做的清理/归档，立刻装回去，装回去之前这段时间没有任何保护
ALTER TABLE core_auditlog ENABLE TRIGGER core_auditlog_append_only;

-- 乙：superuser 会话里关掉本会话的触发器执行（不动表定义，作用域限于这个连接）
SET session_replication_role = replica;
--   ……同一个连接里做完，退出即失效
```

甲要给表加 `ACCESS EXCLUSIVE` 锁——站点在用的话会短暂阻塞对审计表的读写，挑低峰做。**做完读回确认**：`\d core_auditlog` 里 `Triggers` 一栏应重新出现该触发器。

**能挡住的与挡不住的**：挡的是行级 `UPDATE` / `DELETE`（含 ORM 与脚本）。**挡不住**整表级的动作——`TRUNCATE`（`manage.py flush` 走的就是它）、`DROP TABLE`、从备份整库恢复，以及上面两条逃生口。也就是说：留痕不会被某段代码或某个人悄悄改掉一行，但「把库整个换掉」这种级别的操作，任何应用层护栏都拦不住，靠的是备份与权限。

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
