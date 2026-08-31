# 生产环境部署与更新手册

本文档是**生产级标准**的部署与运维手册。只做服务器上快速测试的，请看 `docs/deploy.md`（快速测试部署）。

适用形态：单台 Linux 服务器，PostgreSQL + gunicorn + Nginx + HTTPS，代码只从 git tag 发布。

> 约定：部署目录 `/opt/702platform`，运行账号 `club`，域名以 `club.example.com` 示例，systemd 服务名 `club702`。实际部署时替换为真实值。

---

## 0. 原则

| 原则 | 落地方式 |
|---|---|
| 唯一事实来源 | 服务器上只从 git 取代码（打 tag 的发布版），不在服务器手改任何文件 |
| 可重复 | 首次部署与每次更新走同一套脚本 `deploy/deploy.sh` |
| 可回滚 | 每次发布打 git tag；回滚 = checkout 上一个 tag + `migrate` + 重启 |
| 先备份再动库 | `deploy.sh` 在切换版本前自动备份数据库与媒体 |
| 迁移纪律 | `makemigrations` 只在开发机执行并随代码提交；服务器永远只跑 `migrate` |

---

## 1. 首次部署

### 1.1 服务器基础环境

```bash
# 专用运行账号（不要用 root 跑应用）
sudo useradd -m -s /bin/bash club

# 防火墙：只放行必要端口
sudo ufw allow 22,80,443/tcp

# 基础软件
sudo apt update
sudo apt install nginx postgresql git
```

Python 需要 3.10+（本项目在 3.13 验证）。若系统 Python 过旧：

```bash
sudo apt install python3.13 python3.13-venv
```

### 1.2 PostgreSQL

```bash
sudo -u postgres psql <<'SQL'
CREATE USER club702 WITH PASSWORD '换成随机长密码';
CREATE DATABASE club702 OWNER club702;
SQL
```

把密码记下来，下一步写进 `env.sh`。生成随机串：

```bash
.venv 不存在时可用: openssl rand -base64 36
```

### 1.3 获取代码并安装依赖

```bash
sudo mkdir -p /opt/702platform && sudo chown club:club /opt/702platform
sudo -iu club
git clone <你的仓库地址> /opt/702platform
cd /opt/702platform

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt -r requirements-prod.txt
```

> 仓库在私有位置时的替代做法：本地 `git push` 到服务器上的裸仓库（`git init --bare /opt/702platform.git`），或 `git bundle` 拷贝后 `git clone`。仓库地址本身不要求公网可达。

### 1.4 配置 env.sh（权限必须 600）

```bash
cat > env.sh <<'EOF'
export DJANGO_SECRET_KEY="openssl-rand-base64-36-生成的随机串"
export DJANGO_DEBUG="0"
export DJANGO_ALLOWED_HOSTS="club.example.com"
export DJANGO_SESSION_COOKIE_SECURE="1"
export DJANGO_CSRF_COOKIE_SECURE="1"
export DJANGO_PROXY_SSL_HEADER="1"
export DJANGO_CSRF_TRUSTED_ORIGINS="https://club.example.com"
export DJANGO_DB_ENGINE="django.db.backends.postgresql"
export DJANGO_DB_NAME="club702"
export DJANGO_DB_USER="club702"
export DJANGO_DB_PASSWORD="第 1.2 步的数据库密码"
export DJANGO_DB_HOST="127.0.0.1"
export DJANGO_DB_PORT="5432"
EOF
chmod 600 env.sh
```

配置项说明：

| 变量 | 作用 |
|---|---|
| `DJANGO_SECRET_KEY` | 必须随机、必须保密，泄露需轮换（会使所有会话失效） |
| `DJANGO_DEBUG=0` | 关闭调试页；`check --deploy` 的前提 |
| `DJANGO_ALLOWED_HOSTS` | Host 校验，不带协议和端口 |
| `DJANGO_PROXY_SSL_HEADER=1` | 信任 Nginx 传入的 `X-Forwarded-Proto`（仅当 TLS 由 Nginx 终止时开启） |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | HTTPS 下表单提交的 Origin 校验，带协议 `https://` |

### 1.5 初始化数据库和管理员

```bash
source env.sh
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
```

- 全新空库，管理员需要重新创建；普通成员账号在 `/admin/` 发放。
- 自检：`.venv/bin/python manage.py check --deploy`，生产配置下不应有严重警告。

### 1.6 静态文件、Nginx、HTTPS

```bash
.venv/bin/python manage.py collectstatic --noinput

# Nginx
sudo cp deploy/nginx-club702.conf /etc/nginx/sites-available/club702
sudo vi /etc/nginx/sites-available/club702      # 把 server_name 改为实际域名
sudo ln -s /etc/nginx/sites-available/club702 /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# HTTPS（certbot 会自动改写 Nginx 配置加入 443 与跳转）
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d club.example.com
```

### 1.7 进程托管（systemd）

```bash
# 确认 unit 内的 User/路径与服务名一致后：
sudo cp deploy/club702.service /etc/systemd/system/club702.service
sudo systemctl daemon-reload
sudo systemctl enable --now club702
sudo systemctl status club702
```

### 1.8 上线自检

```bash
curl -i https://club.example.com/            # 期望 200，响应头含 X-Request-ID
curl -I http://club.example.com/             # 期望 301 跳转到 https
journalctl -u club702 -n 20                  # 进程日志无异常
```

浏览器按 `docs/deploy.md` 第 9 节的业务清单冒烟（公开页、强制改密、内部通知分组可见、竞赛报名、设备借还、审计日志只读）。

**当天完成第一份备份**：配置 cron（见第 3 节），手动跑一次 `sudo /opt/702platform/deploy/backup.sh` 确认 `backups/` 出现两个文件。

---

## 2. 后续更新发布

### 2.1 打 tag（开发机）

```bash
# 在 main 分支确认全量测试通过后
git tag -a v1.0.1 -m "发布说明"
git push <remote> main --tags     # 或对服务器裸仓库: git push /opt/702platform.git main --tags
```

tag 命名：`v主.次.修订`。修订位+1 = bug 修复；次位+1 = 新功能；主位+1 = 不兼容变更。每次发布一条 `-m` 说明，作为 CHANGELOG。

### 2.2 发布（服务器，一条命令）

```bash
cd /opt/702platform
./deploy/deploy.sh v1.0.1
```

脚本自动完成六步：**备份 → checkout tag → 装依赖 → 服务器上跑全量测试 → migrate + collectstatic → 重启 + 健康检查**。任何一步失败即中止，生产数据未动。

> 第 4 步在服务器上跑 `manage.py test`：Django 使用临时测试库，等于用服务器真实环境验证了新代码与迁移文件，通过后才真正 `migrate` 生产库。

### 2.3 回滚

```bash
cd /opt/702platform
source env.sh
git checkout v1.0.0
.venv/bin/python manage.py migrate --noinput
sudo systemctl restart club702
```

- 代码层回滚通常不需要动数据库（迁移纪律保证上一版兼容当前库）。
- 若迁移本身造成数据问题：`gunzip -c backups/db-<发布前时间戳>.sql.gz | psql -U club702 club702`（恢复前先停服）。所以**发布前那份备份至少保留到下一次发布成功之后**——脚本按份数保留，不会提前清掉它。

### 2.4 破坏性迁移的两段式纪律

删字段/删表/改字段类型不要与依赖旧字段的功能放在同一次发布：

- 本次发布：加新列、代码双写新旧字段；
- 下次发布：确认稳定后删旧列。

这样任何一版代码都与当版数据库兼容，回滚不需要恢复数据。

---

## 3. 备份与恢复

### 3.1 每日备份（cron）

```bash
sudo crontab -e
# 加入一行（凌晨 3:30 执行）:
30 3 * * * /opt/702platform/deploy/backup.sh >> /opt/702platform/logs/backup.log 2>&1
```

保留 14 份；`backups/` 建议同步到异地（脚本末尾留了 rsync 接口）。

### 3.2 恢复演练（每季度一次）

```bash
# 在测试环境验证备份可用，而不是等事故才发现备份坏了
gunzip -c backups/db-daily-XXXX.sql.gz | psql -U club702 <测试库名>
tar -xzf backups/media-daily-XXXX.tar.gz -C <测试目录>
```

---

## 4. 日常运维

| 事项 | 做法 |
|---|---|
| 应用日志 | `logs/django.log`（10MB×5 轮转）；按 `X-Request-ID` 检索单次请求 |
| 进程日志 | `journalctl -u club702 -f` |
| 服务状态 | `systemctl status club702` |
| 证书续期 | certbot 自动（`systemctl list-timers | grep certbot` 可验证） |
| 拨测监控 | 外部服务打 `https://club.example.com/` 即可，小规模不必上 Prometheus |
| 磁盘 | `df -h` 关注 `mediafiles/`（视频单个上限 500MB）与 `backups/` |

---

## 5. 与快速测试部署（docs/deploy.md）的差异

| 项 | 快速测试 | 生产 |
|---|---|---|
| 数据库 | SQLite（文件） | PostgreSQL |
| 应用服务器 | runserver | gunicorn + systemd |
| 静态/媒体 | Django 自带 | Nginx 直出 |
| HTTPS | 无（HTTP） | certbot 自动签发续期 |
| 代码来源 | tar 包 | git tag |
| 测试 | 本机已测 | 服务器上发布前全量回归 |
| 备份 | 无 | 每日自动 + 发布前自动 |
| 密钥 | env.sh（DEBUG=1） | env.sh 600 权限（DEBUG=0 + HTTPS Cookie） |
