# 生产环境部署与更新手册

本文档是**生产级标准**的部署与运维手册。核心思路：

- **一次部署脚本** `deploy/install.sh`：环境检测 → 配置检测 → 全自动搭建（建库、迁移、超管、systemd 服务、Nginx、备份定时器、健康检查）。
- **检测到环境或配置不符合就中止**，脚本绝不会自动下载或安装任何软件——缺什么、怎么补，提示都写明白了。
- 数据库**默认 PostgreSQL**，数据库名/用户/密码/密钥/超管等系统信息全部用 `<尖括号>` 占位符，由部署者填写；端口等应用信息才给默认值。
- 快速测试部署请见 `docs/deploy.md`。

适用形态：单台 Linux 服务器，PostgreSQL + gunicorn + Nginx + systemd + HTTPS。

> 约定：部署目录 `/opt/702platform`（示例），域名以 `club.example.com` 示例，服务名 `club702`。实际按环境替换。

---

## 1. 首次部署（一次脚本，共 10 步自动完成）

### 1.1 前置：把依赖环境准备好（脚本只检测，不替你装）

```bash
# 以 root 或 sudo 执行
sudo apt update
sudo apt install nginx postgresql python3 python3-venv python3-pip git
```

### 1.2 部署专用户（脚本要求 DEPLOY_SYSTEM_USER 真实存在）

```bash
sudo useradd -m -s /bin/bash club      # 例：系统用户 club
```

### 1.3 获取代码（服务器只从 git 取，可追溯）

```bash
sudo mkdir -p /opt/702platform && sudo chown club:club /opt/702platform
sudo -iu club
cd /opt/702platform
git clone <你的仓库地址> .   # 或已有裸仓库 push 后 clone
```

### 1.4 创建虚拟环境并安装依赖

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt -r requirements-prod.txt
```

### 1.5 配置 env.sh（复制模板并填写占位符）

```bash
cp deploy/env.template env.sh
chmod 600 env.sh
vi env.sh
```

`env.sh` 中这几类必须替换 `<尖括号>`：

| 配置项 | 填写示例 | 说明 |
|---|---|---|
| `DJANGO_SECRET_KEY` | `openssl rand -base64 36` 的输出 | 密钥，泄露需轮换 |
| `DJANGO_ALLOWED_HOSTS` | `club.example.com` | Host 校验，不带协议端口，逗号分隔 |
| `DJANGO_DB_NAME` | `club702` | 数据库名（脚本自动创建） |
| `DJANGO_DB_USER` | `club702` | 数据库账号（脚本自动创建） |
| `DJANGO_DB_PASSWORD` | 随机长串 | 数据库密码 |
| `DJANGO_SUPERUSER_USERNAME` / `_EMAIL` / `_PASSWORD` | `admin` / 邮箱 / 随机串 | 首次部署自动创建的超管 |
| `DEPLOY_SERVER_NAME` | `club.example.com` | Nginx `server_name` 与健康检查入口 |
| `DEPLOY_SYSTEM_USER` | `club` | 运行应用与备份的 Linux 系统用户 |

有默认值、一般不改的项：

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `DJANGO_DB_ENGINE` | `django.db.backends.postgresql` | **默认就 PostgreSQL** |
| `DJANGO_APP_HOST` / `DJANGO_APP_PORT` | `127.0.0.1` / `8000` | gunicorn 监听地址/端口 |
| `DJANGO_DB_HOST` / `DJANGO_DB_PORT` | `127.0.0.1` / `5432` | PostgreSQL 地址/端口 |
| `DJANGO_BACKUP_SCHEDULE` | `daily` | **备份频次**（systemd OnCalendar 语法） |
| `DJANGO_BACKUP_RETAIN` | `14` | 备份保留份数 |
| `DJANGO_DEBUG` / Cookie / Proxy 项 | 安全默认 | HTTPS 就绪后按需改动 |

### 1.6 运行首次部署脚本（会自动完成建库、迁移、超管、服务、Nginx、备份定时、健康检查）

```bash
cd /opt/702platform
sudo ./deploy/install.sh
```

脚本会依次：

1. 校验 env.sh 无残留占位符（有则列出并中止）
2. 检测依赖环境：python3≥3.10、venv、Django/DRF/bleach/markdown/Pillow/psycopg/gunicorn、systemd、Nginx、PostgreSQL、备份频次是否为合法 systemd 日历表达式、部署用户存在
   —— **任何一项不满足：打印缺少什么 + 补什么命令，然后中止**，绝不自动安装
3. 创建数据库角色与数据库（PostgreSQL，幂等）
4. `migrate`、`collectstatic`
5. 幂等创建超级管理员
6. 注册 `club702.service`（应用）与 `club702-backup.{service,timer}`（备份定时器），`enable --now` 启动
7. 生成 Nginx 站点 `sites-available/club702` 并 `nginx -t` + reload
8. 健康检查（`curl -H "Host: <server_name>" http://127.0.0.1:8000/`）

### 1.7 HTTPS（certbot 自动改写 Nginx 并续期）

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d club.example.com
```

启用 HTTPS 后回到 `env.sh` 打开以下安全项，并 `systemctl restart club702`：

```bash
DJANGO_SESSION_COOKIE_SECURE=1
DJANGO_CSRF_COOKIE_SECURE=1
DJANGO_PROXY_SSL_HEADER=1
DJANGO_CSRF_TRUSTED_ORIGINS=https://club.example.com
```

### 1.8 上线自检（走一遍业务冒烟）

`docs/deploy.md` 第 9 节的业务清单：公开页、强制改密、内部通知分组可见性、竞赛报名、设备借还、审计日志只读。浏览器访问 `http://<server_name>/`。

---

## 2. 后续更新发布

### 2.1 打 tag（开发机）

```bash
git tag -a v1.0.1 -m "发布说明"
git push <remote> main --tags
```

命名 `v主.次.修订`：修订位+1=修复；次位+1=新功能；主位+1=不兼容变更。

### 2.2 发布（服务器，一条命令）

```bash
cd /opt/702platform
sudo -u club bash -c './deploy/deploy.sh v1.0.1'   # club = DEPLOY_SYSTEM_USER
```

脚本自动完成：备份数据库与媒体（保留 RETAIN 份）→ checkout tag → 升级依赖 → migrate + collectstatic → 重启 → 健康检查。任何一步失败中止。

### 2.3 回滚

```bash
cd /opt/702platform
set -a; source env.sh; set +a
git checkout v1.0.0
.venv/bin/python manage.py migrate --noinput
systemctl restart club702
```

- 代码层回滚通常不需要动数据库（迁移纪律保证上一版兼容当前库）。
- 迁移本身出问题：`gunzip -c backups/db-<发布前>.sql.gz | PGPASSWORD=... psql -U $DJANGO_DB_USER $DJANGO_DB_NAME`（恢复前先停服）。发布前那份备份保留 RETAIN 份内不会提前清掉。

### 2.4 破坏性迁移两段式纪律

删字段/删表/改类型不要与依赖旧字段的功能同一次发布：先加新列+双写，下次发布再删旧列。保证任何一版代码与当版数据库兼容。

---

## 3. 备份（systemd timer 驱动）

### 3.1 为什么备份不用 cron、也不放进应用服务

- **应用服务 `club702.service` 是常驻 gunicorn 进程**，不能塞备份逻辑——那是"需要周期性触发的一次性任务"，放进常驻进程会让定时与阻塞逻辑纠缠。
- 正确拆法：独立的 **`club702-backup.service`（oneshot）+ `club702-backup.timer`（定时触发）**，与 cron 相比：统一由 systemd 管理、`systemctl list-timers` 可查、能设置 `Persistent=true`（关机的错过的备份开机后补跑）。

### 3.2 频次配置与查看

```bash
# 频次就是 env.sh 里的 DJANGO_BACKUP_SCHEDULE（systemd OnCalendar 语法）
#   默认 daily            -> 每天 00:00
#   每天 3 点              -> *-*-* 03:00:00
#   周一到周五 2 点        -> Mon..Fri *-*-* 02:00:00
#   每小时                -> hourly
#   每 30 分钟            -> *:0/30

systemctl list-timers | grep club702        # 下次触发时间
systemctl status club702-backup.timer
```

改频次后重载：

```bash
sed -i 's|^DJANGO_BACKUP_SCHEDULE=.*|DJANGO_BACKUP_SCHEDULE=*-*-* 03:00:00|' env.sh
systemctl restart club702-backup.timer      # 重新读取 timer 配置
```

### 3.3 手动备份与恢复

```bash
sudo -u club bash -c "cd /opt/702platform && source env.sh && ./deploy/backup.sh"

# 恢复数据库
gunzip -c backups/db-XXXX.sql.gz | PGPASSWORD=... psql -U club702 club702
# 恢复媒体
tar -xzf backups/media-XXXX.tar.gz -C /opt/702platform
```

保留份数由 `DJANGO_BACKUP_RETAIN` 控制（默认 14）。`backups/` 建议异地同步（脚本结尾留了 rsync 示意）。

恢复演练（季度一次）：在测试环境解压即验证备份可用。

---

## 4. 日常运维

| 事项 | 做法 |
|---|---|
| 应用日志 | `journalctl -u club702 -f`；应用内部日志 `logs/django.log` |
| 服务状态 | `systemctl status club702` |
| 证书续期 | certbot 自动（`systemctl list-timers | grep certbot` 验证） |
| 拨测 | 外部打 `https://club.example.com/`（小规模就够，不必上 Prometheus） |
| 磁盘 | 关注 `mediafiles/`（视频单个≤500MB）、`backups/`、`logs/` |

---

## 5. 与快速测试部署（docs/deploy.md）的差异

| 项 | 快速测试 | 生产 |
|---|---|---|
| 数据库 | SQLite（默认） | **PostgreSQL（默认）** |
| 应用进程 | runserver | gunicorn + systemd |
| 静态/媒体 | Django 自带 | Nginx 直出 |
| HTTPS | 无 | certbot 自动 |
| 部署方式 | 手动逐条命令 | **`./deploy/install.sh` 一次完成** |
| 配置 | 环境变量直接给 | env.sh 占位符 + 校验 + 中止 |
| 备份 | 无 | systemd timer 每日自动 |
| 系统信息 | 全部换成真实值 | 占位符 `<...>` 必须替换才放行 |

---

## 6. install.sh 检测策略问答

- **脚本会自己下载安装吗？** 不会。任何缺失项只打印"缺什么 + 怎么补"，然后退出，等待部署者补齐后重跑。
- **占位符没替换会怎样？** `grep` 逐项扫出所有仍为 `<...>` 的配置，逐个列出并中止。
- **重复运行安全吗？** 安全。创建数据库角色/库、建超管都做了幂等判断。
- **备份必须和系统服务同机吗？** 备份 timer 依赖本机 `pg_dump` 与媒体目录，单服务器形态下就在本机；异地拷贝可加 rsync。