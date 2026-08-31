# 服务器部署与测试说明

本文档说明如何把平台源码包上传到一台 Linux 服务器并运行测试。标注「本机」的命令在开发机执行，其余命令默认在服务器上、部署目录内执行。

> 部署包由源码目录打包而成，除新增的本文件外，内容与 `main` 分支提交一一对应，可用提交号追溯。

---

## 1. 部署包内容

| 包含 | 说明 |
|---|---|
| `manage.py`、`requirements.txt`、`README.md`、`docs/` | 入口、依赖清单和文档 |
| `config/`、`accounts/`、`notices/`、`content/`、`media/`、`projects/`、`competitions/`、`equipment/`、`core/` | 全部应用源码与数据库迁移 |
| `templates/`、`static/` | 模板与静态资源 |

| 不包含 | 原因 |
|---|---|
| `db.sqlite3` | 部署后在服务器执行 `migrate` 重新创建，本地数据不随包上传 |
| `logs/` | `settings.py` 启动时自动创建 |
| `mediafiles/` | 首次上传媒体时自动创建 |
| `.venv/`、`.git/`、`__pycache__/`、`staticfiles/`、历史压缩包 | 本机生成内容或非运行必需 |

## 2. 服务器环境要求

- Linux 服务器（按 Debian/Ubuntu 系说明，其他发行版命令类似）。
- Python 3.10 及以上（本项目在 Python 3.13 上验证）：`python3 --version`。
- venv 支持：`sudo apt install python3-venv`（多数镜像已自带）。

## 3. 上传与解压

本机执行（把部署包上传到服务器）：

```bash
scp 702platform-deploy-<commit>.tar.gz user@服务器IP:/opt/
```

服务器执行：

```bash
mkdir -p /opt/702platform
tar -xzf /opt/702platform-deploy-<commit>.tar.gz -C /opt/702platform
cd /opt/702platform
```

- 部署目录可以任选，下文统一以 `/opt/702platform` 为例。
- 运行账号需要对该目录有写权限（数据库、日志、上传媒体都写在这里）。

完整性校验（可选）：

```bash
sha256sum /opt/702platform-deploy-<commit>.tar.gz   # 与本机生成的校验值对比
```

## 4. 创建虚拟环境并安装依赖

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

## 5. 配置环境变量

先生成一个随机密钥（只执行一次，把输出保存好）：

```bash
.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(50))'
```

写入 `env.sh` 并按部署方式二选一填写：

```bash
vi env.sh
```

方案 A：快速联调测试（DEBUG 开启，Django 自己提供静态/媒体服务，无需 Nginx）：

```bash
export DJANGO_SECRET_KEY="粘贴上面生成的随机串"
export DJANGO_DEBUG="1"
export DJANGO_ALLOWED_HOSTS="服务器IP"
```

方案 B：接近生产的验证（DEBUG 关闭，gunicorn + Nginx，见第 7、8 节）：

```bash
export DJANGO_SECRET_KEY="粘贴上面生成的随机串"
export DJANGO_DEBUG="0"
export DJANGO_ALLOWED_HOSTS="服务器域名"
export DJANGO_SESSION_COOKIE_SECURE="1"
export DJANGO_CSRF_COOKIE_SECURE="1"
```

说明：

- `DJANGO_ALLOWED_HOSTS` 写主机名或 IP，不带端口和协议；多个值用英文逗号分隔。
- `DEBUG=1` 会向访客暴露配置和堆栈，只用于临时测试，测完尽快切到方案 B。
- 之后每次登录服务器操作前先 `source env.sh`；用 systemd 托管时由 `EnvironmentFile` 自动加载。

## 6. 初始化数据库和管理员

```bash
source env.sh
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
```

- 服务器上是全新数据库，需要在 `createsuperuser` 里重新创建管理员。
- 普通成员账号统一在 `/admin/` 里创建（不开放注册）。
- 可选的生产配置自检：`.venv/bin/python manage.py check --deploy`（方案 A 下出现安全警告是预期现象）。

## 7. 启动服务

### 方案 A：runserver 快速验证

```bash
.venv/bin/python manage.py runserver 0.0.0.0:8000
```

- 浏览器访问 `http://服务器IP:8000/`。
- 云服务器需要先在安全组/防火墙放行 8000 端口。
- 断开 SSH 会中断服务，长时间观察可放进 `tmux` / `screen` 里运行。

### 方案 B：gunicorn（推荐，配合 Nginx）

```bash
.venv/bin/python -m pip install gunicorn
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 2
```

- `collectstatic` 把静态文件收集到 `staticfiles/`，交给 Nginx 服务。
- gunicorn 只监听本机回环地址，对外统一走 Nginx。

长期运行用 systemd 托管（`/etc/systemd/system/club702.service`）：

```ini
[Unit]
Description=Competition club platform (gunicorn)
After=network.target

[Service]
User=运行账号
WorkingDirectory=/opt/702platform
EnvironmentFile=/opt/702platform/env.sh
ExecStart=/opt/702platform/.venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 2
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now club702
sudo systemctl status club702   # 查看运行状态
```

## 8. Nginx 参考配置（方案 B）

```nginx
server {
    listen 80;
    server_name _;

    client_max_body_size 520m;   # 放行最大 500MB 的视频上传

    location /static/ {
        alias /opt/702platform/staticfiles/;
    }
    location /media/ {
        alias /opt/702platform/mediafiles/;
    }
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

已知限制：

- 审计日志记录的来源 IP 取自 `REMOTE_ADDR`，经 Nginx 代理后统一记为 `127.0.0.1`；如需真实来源 IP，需要后续增加可信代理配置（见架构文档待定项）。
- 若启用 HTTPS 后出现 CSRF 验证失败，需要补充 `SECURE_PROXY_SSL_HEADER` 与 `CSRF_TRUSTED_ORIGINS` 配置（当前 `config/settings.py` 尚未包含这两项）。

## 9. 部署后验证清单

命令行冒烟：

```bash
curl -i http://127.0.0.1:8000/          # 期望 200，响应头含 X-Request-ID
curl -i http://127.0.0.1:8000/login/    # 期望 200
```

浏览器按业务流程过一遍：

1. 公开首页、公开通知列表与详情（未登录）。
2. 管理员登录 `/admin/`，创建成员账号并加入用户组。
3. 成员首次登录被强制改密，改密后进入成员中心、维护个人资料。
4. 管理员发布内部通知并绑定用户组：组内成员可见、组外成员与访客不可见。
5. 项目组维护、组长竞赛报名、设备借用与归还各走一遍。
6. `/admin/core/auditlog/` 能看到上述操作的审计记录，且为只读。

日志位于 `logs/django.log`（10MB 轮转，保留 5 份）；排查单次请求时用响应头里的 `X-Request-ID` 到日志里搜索。

## 10. 常见问题

| 现象 | 处理 |
|---|---|
| `DisallowedHost` | 把访问用的 IP/域名补进 `DJANGO_ALLOWED_HOSTS` 后重启（不带端口） |
| DEBUG=0 时页面无样式 | 忘记 `collectstatic`，或 Nginx 未正确映射 `/static/` |
| DEBUG=0 时 `/media/` 404 | Nginx 未映射 `/media/`；方案 A 下 runserver 自带媒体服务无此问题 |
| 上传视频返回 413 | Nginx `client_max_body_size` 太小 |
| `no such table` | 未执行 `migrate`，或 `DJANGO_DB_NAME` 指向了别的路径 |
| 看不到内部通知 | 检查成员是否完成首次改密、是否属于通知绑定的用户组 |

## 11. 与本地开发的差异

- 数据不随包迁移：服务器从空库开始，重新建管理员和业务数据。
- 上传媒体保存在服务器 `mediafiles/uploads/`，测试期注意磁盘占用（单个视频上限 500MB）。
- SQLite 足够测试使用；切换 PostgreSQL 的步骤见 `docs/project-guide.md` 第 7.3 节。
- 长期运行建议用 systemd/supervisor 托管进程，并规划数据库与媒体目录的定期备份。

## 附录：打包方法（本机执行）

```bash
cd /home/alen/work/702platform
tar -zcf ../702platform-deploy-$(git rev-parse --short HEAD).tar.gz \
  --exclude='.git' --exclude='.venv' --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='db.sqlite3' --exclude='logs' --exclude='mediafiles' --exclude='staticfiles' \
  --exclude='社团评审系统_发布版.zip' \
  .
```
