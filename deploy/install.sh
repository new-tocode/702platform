#!/usr/bin/env bash
# ============================================================
# 702platform 首次部署脚本
#
# 职责:
#   1. 检测依赖环境 —— 任何不符合项只打印提示并中止，绝不自动下载/安装
#   2. 检测配置占位符 —— 用户未替换的 <...> 项打印提示并中止
#   3. 全部就绪后自动完成:
#        建数据库/账号 -> migrate -> 创建超级管理员 -> collectstatic
#        -> 注册 systemd 服务(应用+备份timer) -> 配置 Nginx -> 启动并健康检查
#
# 用法: sudo ./deploy/install.sh
#   需要 root 或 sudo，因为要写 /etc/systemd、/etc/nginx、操作 postgres。
# ============================================================
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$APP_DIR/env.sh"
TEMPLATE="$APP_DIR/deploy/env.template"

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; CYN=$'\033[36m'; RST=$'\033[0m'
info() { echo "${CYN}==> $*${RST}"; }
ok()   { echo "${GRN}  OK  $*${RST}"; }
warn() { echo "${YEL}  !!  $*${RST}" >&2; }
fail() { echo "${RED}==> $*${RST}" >&2; }

# ---------- 0. 运行者必须是可写系统目录的账号 ----------
if [[ "$(id -u)" -ne 0 ]]; then
    fail "请用 root 运行本脚本（例如 sudo ./deploy/install.sh）"
    exit 1
fi

# ---------- 1. env.sh 必须存在 ----------
if [[ ! -f "$ENV_FILE" ]]; then
    cp "$TEMPLATE" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    fail "首次运行，已从模板创建 $ENV_FILE"
    fail "请编辑该文件，把所有 <尖括号> 占位符替换为真实值后重新运行本脚本"
    exit 1
fi

# env.sh 里是数据库口令、SECRET_KEY 与超管口令。cp 出来的文件权限随 umask，
# 可能是 644——同一台机器上的其它低权账号就能读走全部机密。每次运行都收紧一次，
# 历史上的宽权限也就跟着修好了。
if [[ "$(stat -c '%a' "$ENV_FILE")" != "600" ]]; then
    chmod 600 "$ENV_FILE"
    ok "已将 $ENV_FILE 权限收紧为 600（内含数据库口令与 SECRET_KEY）"
fi

# ---------- 2. 配置检测：占位符未替换则全部列出并中止 ----------
UNFILLED=$(grep -nE '^[A-Za-z_]+=<[^>]+>[[:space:]]*$' "$ENV_FILE" || true)
if [[ -n "$UNFILLED" ]]; then
    fail "env.sh 中仍有未替换的占位符配置项（请逐项填写后再运行）:"
    while IFS= read -r line; do
        var="${line%%=*}"
        fail "  - $var"
    done <<< "$UNFILLED"
    exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

# 校验必须在 env.sh 中显式存在的关键项
for var in DJANGO_SECRET_KEY DJANGO_ALLOWED_HOSTS DJANGO_DB_NAME \
           DJANGO_DB_USER DJANGO_DB_PASSWORD DJANGO_SUPERUSER_USERNAME \
           DJANGO_SUPERUSER_EMAIL DJANGO_SUPERUSER_PASSWORD \
           DEPLOY_DOMAIN DEPLOY_PUBLIC_IP DEPLOY_SYSTEM_USER DJANGO_BACKUP_SCHEDULE \
           DJANGO_CSRF_TRUSTED_ORIGINS; do
    if [[ -z "${!var:-}" ]]; then
        fail "env.sh 缺少必需配置项 $var（请参照 deploy/env.template）"
        exit 1
    fi
done

# 上面那道「非空」检查拦不住一种情况：值形如 https://<DOMAIN>,https://<PUBLIC_IP>
# ——非空，但尖括号还在，等于没填。模板里这一项是逗号分隔的多个来源，不符合上面
# 那条 UNFILLED 正则（它只管「整行就是一个 <...>」），所以漏得过去。
# 而漏填的后果是静默的：CSRF_TRUSTED_ORIGINS 变成一串无效来源，表单提交照样 403。
if [[ "$DJANGO_CSRF_TRUSTED_ORIGINS" == *"<"* || "$DJANGO_CSRF_TRUSTED_ORIGINS" == *">"* ]]; then
    fail "DJANGO_CSRF_TRUSTED_ORIGINS 里还有未替换的 <> 占位符：$DJANGO_CSRF_TRUSTED_ORIGINS"
    fail "请写上成员实际访问的每个入口（含协议），例如 https://club.example.com,https://1.2.3.4"
    exit 1
fi

# ---------- 3. 依赖环境检测（只提示，不自动安装） ----------
MISSING=()
need_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        MISSING+=("缺少系统命令 $1（$2）")
    fi
}

# PostgreSQL 工具不一定在默认 PATH：RHEL/PGDG 装在 /usr/pgsql-<ver>/bin，且只为
# psql/pg_dump 等建了 /usr/bin alternatives，pg_isready/postgres 往往取不到。
# 这里自动探测 PG 的 bin 目录并前置到 PATH，避免把已安装的组件误报成缺失。
if ! command -v pg_isready >/dev/null 2>&1 || ! command -v psql >/dev/null 2>&1 \
   || ! command -v postgres >/dev/null 2>&1; then
    PG_BIN=""
    # 高版本目录优先（sort -rV），确保取到与 server 匹配的工具
    # shellcheck disable=SC2046
    for d in $(ls -d /usr/pgsql-*/bin /usr/lib/postgresql/*/bin /usr/local/pgsql/bin /opt/pgsql*/bin 2>/dev/null | sort -rV); do
        if [[ -x "$d/pg_isready" || -x "$d/psql" || -x "$d/postgres" ]]; then
            PG_BIN="$d"
            break
        fi
    done
    if [[ -n "$PG_BIN" ]]; then
        export PATH="$PG_BIN:$PATH"
        info "已将 PostgreSQL 工具目录加入 PATH: $PG_BIN"
    fi
fi

need_cmd systemctl      "systemd 未启用，本部署依赖 systemd"
need_cmd nginx          "如 Ubuntu: sudo apt install nginx"
need_cmd psql           "PostgreSQL 客户端，如 Ubuntu: sudo apt install postgresql-client"
need_cmd pg_isready     "PostgreSQL 客户端工具，如 Ubuntu: sudo apt install postgresql-client"
need_cmd msgfmt         "界面英文翻译的编译工具（gettext 包），如 Ubuntu: sudo apt install gettext"
need_cmd sudo           "本脚本需要 sudo 权限"

# PostgreSQL 服务本身
need_cmd postgres       "PostgreSQL 服务端未安装，如 Ubuntu: sudo apt install postgresql"
# Python 版本 >= 3.10（仅使用项目虚拟环境；不检测/不使用系统 python）
if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
    MISSING+=("缺少虚拟环境 $APP_DIR/.venv（请先执行: python3 -m venv .venv）")
else
    PY_VER="$("$APP_DIR/.venv/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    if ! "$APP_DIR/.venv/bin/python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
        MISSING+=("Python 版本过低($PY_VER)，需要 >= 3.10")
    fi
fi

# 项目依赖（不自动 pip install，只检测）
for pkg in django rest_framework bleach markdown PIL psycopg gunicorn; do
    if ! "$APP_DIR/.venv/bin/python" -c "import $pkg" >/dev/null 2>&1; then
        MISSING+=("Python 依赖未安装: $pkg（请先执行: $APP_DIR/.venv/bin/python -m pip install --require-hashes -r requirements.txt -r requirements-prod.txt）")
    fi
done

# 备份频次校验（systemd OnCalendar 语法）
if command -v systemd-analyze >/dev/null 2>&1; then
    if ! systemd-analyze calendar "$DJANGO_BACKUP_SCHEDULE" >/dev/null 2>&1; then
        MISSING+=("DJANGO_BACKUP_SCHEDULE 不是合法的 systemd 日历表达式（如 daily、*-*-* 03:00:00）")
    fi
fi

# 部署目标用户必须真实存在
if ! id -u "$DEPLOY_SYSTEM_USER" >/dev/null 2>&1; then
    MISSING+=("系统用户 $DEPLOY_SYSTEM_USER 不存在（请先: sudo useradd -m -s /bin/bash $DEPLOY_SYSTEM_USER）")
fi

if [[ "${#MISSING[@]}" -gt 0 ]]; then
    fail "依赖环境检查未通过，以下项需要你先手动处理（本脚本不会自动安装）:"
    for m in "${MISSING[@]}"; do
        fail "  - $m"
    done
    fail "补齐以上项目后重新运行本脚本"
    exit 1
fi
ok "依赖环境检查通过"

# ---------- 4. 数据库就绪（PostgreSQL） ----------
# 探测 PostgreSQL 的 systemd 服务单元名（随发行版与 PG 版本而变，故不硬编码）:
#   Debian/Ubuntu → postgresql.service（官方包提供的 meta 单元）
#   RHEL/PGDG     → postgresql-<主版本>.service（如 postgresql-16.service）
PG_SERVICE="$(systemctl list-unit-files --type=service --no-pager 2>/dev/null \
    | awk '/^postgresql\.service[[:space:]]/ {deb=$1} /^postgresql-[0-9]+\.service[[:space:]]/ {if (!ver) ver=$1} END {print (deb ? deb : ver)}')"
if [[ -z "$PG_SERVICE" ]]; then
    PG_SERVICE="postgresql.service"
    warn "未探测到 PostgreSQL 服务单元，回退为 $PG_SERVICE（可用 systemctl list-unit-files | grep postgres 核对）"
fi
info "PostgreSQL 服务单元: $PG_SERVICE"

info "确保 PostgreSQL 服务运行中"
if ! systemctl is-active "$PG_SERVICE" >/dev/null 2>&1; then
    systemctl start "$PG_SERVICE" 2>/dev/null || true
fi

# Django 5.2 要求 PostgreSQL >= 14
info "检查 PostgreSQL 版本（Django 5.2 要求 >= 14）"
PG_VER_NUM="$(sudo -u postgres psql -tAc 'SHOW server_version_num' 2>/dev/null | tr -d '[:space:]' || true)"
if [[ -z "$PG_VER_NUM" ]]; then
    warn "无法读取 PostgreSQL 版本号，跳过版本检查（请确认 server 版本 >= 14）"
else
    PG_MAJOR=$((PG_VER_NUM / 10000))
    if (( PG_MAJOR < 14 )); then
        fail "PostgreSQL 版本过低（主版本 $PG_MAJOR，Django 5.2 要求 >= 14），请先升级 PostgreSQL 再运行本脚本"
        fail "升级参考: 添加 PGDG 官方源（https://www.postgresql.org/download/linux/）后安装 PostgreSQL 16"
        exit 1
    elif (( PG_MAJOR < 16 )); then
        warn "PostgreSQL $PG_MAJOR 可满足 Django 5.2（>= 14），但建议升级到 16 以获得更佳支持与性能"
    else
        ok "PostgreSQL $PG_MAJOR 满足要求（>= 14）"
    fi
fi

# 会话认证统一 scram-sha-256：密码以 scram 存储，pg_hba 对本地 TCP 也要求 scram
info "确保数据库角色 $DJANGO_DB_USER 存在（密码 scram-sha-256 存储）"
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DJANGO_DB_USER'" | grep -q 1; then
    # CREATEDB: 允许 Django 测试(`manage.py test`)创建临时测试库
    sudo -u postgres psql -c "SET password_encryption = 'scram-sha-256'; CREATE ROLE \"$DJANGO_DB_USER\" LOGIN CREATEDB PASSWORD '$DJANGO_DB_PASSWORD'"
    ok "已创建数据库角色 $DJANGO_DB_USER"
else
    # 已存在则按当前 env 密码重设，确保以 scram 加密存储
    sudo -u postgres psql -c "SET password_encryption = 'scram-sha-256'; ALTER ROLE \"$DJANGO_DB_USER\" PASSWORD '$DJANGO_DB_PASSWORD'"
    info "数据库角色 $DJANGO_DB_USER 已存在，密码已按 scram-sha-256 刷新"
fi

# pg_hba.conf：本地 TCP(127.0.0.1 / ::1) 认证方法统一改为 scram-sha-256 并重载
HBA_FILE="$(sudo -u postgres psql -tAc 'SHOW hba_file' 2>/dev/null | tr -d '[:space:]' || true)"
if [[ -n "$HBA_FILE" && -f "$HBA_FILE" ]]; then
    sudo sed -E -i 's|^[[:space:]]*(host[[:space:]]+all[[:space:]]+all[[:space:]]+127\.0\.0\.1/32[[:space:]]+)[a-zA-Z0-9_-]+$|\1scram-sha-256|' "$HBA_FILE"
    sudo sed -E -i 's|^[[:space:]]*(host[[:space:]]+all[[:space:]]+all[[:space:]]+::1/128[[:space:]]+)[a-zA-Z0-9_-]+$|\1scram-sha-256|' "$HBA_FILE"
    sudo -u postgres psql -c 'SELECT pg_reload_conf()' >/dev/null 2>&1 || true
    ok "pg_hba.conf 已启用 scram-sha-256 认证"
else
    warn "无法定位 pg_hba.conf，请手工确认 127.0.0.1/::1 使用 scram-sha-256 认证"
fi

info "确保数据库 $DJANGO_DB_NAME 存在"
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DJANGO_DB_NAME'" | grep -q 1; then
    sudo -u postgres createdb -O "$DJANGO_DB_USER" "$DJANGO_DB_NAME"
    ok "已创建数据库 $DJANGO_DB_NAME"
else
    info "数据库 $DJANGO_DB_NAME 已存在，跳过"
fi

run_as_app() {
    sudo -u "$DEPLOY_SYSTEM_USER" env "PATH=$APP_DIR/.venv/bin:$PATH" \
        "HOME=/home/$DEPLOY_SYSTEM_USER" \
        bash -c "cd '$APP_DIR' && set -a && source '$ENV_FILE' && set +a && $*"
}

# ---------- 5. migrate ----------
info "执行数据库迁移"
run_as_app .venv/bin/python manage.py migrate --noinput
ok "迁移完成"

# ---------- 6. 超级管理员（幂等） ----------
info "确保超级管理员存在"
SUPER_OUTPUT="$(run_as_app .venv/bin/python manage.py createsuperuser --noinput 2>&1 || true)"
case "$SUPER_OUTPUT" in
  *already*|*exists*|*used*)
      info "超级管理员 $DJANGO_SUPERUSER_USERNAME 已存在，跳过"
      ;;
  "")
      ok "已创建超级管理员 $DJANGO_SUPERUSER_USERNAME"
      ;;
  *)
      warn "$SUPER_OUTPUT"
      ;;
esac

# ---------- 7. staticfiles 与界面翻译 ----------
info "收集静态文件"
run_as_app .venv/bin/python manage.py collectstatic --noinput >/dev/null
ok "静态文件已收集到 staticfiles/"

# 界面英文的 .mo 由 .po 现编（不进版本库），缺 msgfmt 在依赖检测那一步就中止了
info "编译界面翻译（英文）"
run_as_app .venv/bin/python manage.py compilemessages -l en
ok "界面翻译已编译"

# 备份目录。推荐 /var/backups/club702（见 env.template 的说明）——外置目录不在
# systemd 给应用进程的可写范围里，被攻陷的 Web 应用碰不到备份。本脚本有 sudo，
# 正好负责那一次性的创建；之后 backup.sh 会自己收紧权限、自己判断可写性。
#
# 默认值与 env.template 保持一致：env.sh 里填了什么就用什么，没填则退回应用目录内。
BACKUP_DIR="${DJANGO_BACKUP_DIR:-/var/backups/club702}"
info "确保备份目录存在"
sudo mkdir -p "$BACKUP_DIR"
sudo chown "$DEPLOY_SYSTEM_USER:$DEPLOY_SYSTEM_USER" "$BACKUP_DIR"
sudo chmod 700 "$BACKUP_DIR"
ok "备份目录就绪: $BACKUP_DIR"
if [[ "$BACKUP_DIR" == "$APP_DIR"/* ]]; then
    warn "备份目录在应用目录内：systemd 给了应用进程该目录的写权限，"
    warn "被攻陷的 Web 应用能删改备份。建议在 env.sh 里设"
    warn "DJANGO_BACKUP_DIR=/var/backups/club702 后重跑本脚本。"
fi

# 受保护上传件的目录：backup.service 的 ReadOnlyPaths 与应用的写入都要它存在
info "确保受保护上传目录存在"
sudo mkdir -p "$APP_DIR/protected_media"
sudo chown "$DEPLOY_SYSTEM_USER:$DEPLOY_SYSTEM_USER" "$APP_DIR/protected_media"
ok "受保护上传目录就绪: $APP_DIR/protected_media"

# ---------- 8. 注册 systemd 服务 ----------
info "注册 systemd 服务与备份定时器"

# server_name 使用「域名 + 公网IP」两项（env.sh 必填）
NGINX_SERVER_NAME="$DEPLOY_DOMAIN $DEPLOY_PUBLIC_IP"
RENDER=(
    -e "s|@@APP_DIR@@|$APP_DIR|g"
    -e "s|@@APP_USER@@|$DEPLOY_SYSTEM_USER|g"
    -e "s|@@APP_HOST@@|$DJANGO_APP_HOST|g"
    -e "s|@@APP_PORT@@|$DJANGO_APP_PORT|g"
    -e "s|@@SERVER_NAME@@|$NGINX_SERVER_NAME|g"
    -e "s|@@SSL_CERT_PATH@@|${SSL_CERT_PATH:-}|g"
    -e "s|@@SSL_KEY_PATH@@|${SSL_KEY_PATH:-}|g"
    -e "s|@@BACKUP_SCHEDULE@@|$DJANGO_BACKUP_SCHEDULE|g"
    -e "s|@@BACKUP_RETAIN@@|$DJANGO_BACKUP_RETAIN|g"
    -e "s|@@BACKUP_DIR@@|${DJANGO_BACKUP_DIR:-/var/backups/club702}|g"
    -e "s|@@VENV@@|$APP_DIR/.venv|g"
    -e "s|@@PG_SERVICE@@|${PG_SERVICE:-postgresql.service}|g"
)

apply_template() {
    sed "${RENDER[@]}" "$1" > "$2"
    chmod "$3" "$2"
}

apply_template "$APP_DIR/deploy/club702.service"      "/etc/systemd/system/club702.service"      644
apply_template "$APP_DIR/deploy/club702-backup.service" "/etc/systemd/system/club702-backup.service" 644
apply_template "$APP_DIR/deploy/club702-backup.timer" "/etc/systemd/system/club702-backup.timer"  644

systemctl daemon-reload
systemctl enable --now club702.service
systemctl enable --now club702-backup.timer
ok "已启用 club702.service（应用）与 club702-backup.timer（每日备份）"

# ---------- 9. 配置 Nginx（先识别系统类型，再选择配置文件路径） ----------
info "配置 Nginx"
OS_ID="unknown"
if [[ -r /etc/os-release ]]; then
    OS_ID="$(awk -F= '/^ID=/{gsub(/["\r]/,"",$2); print $2}' /etc/os-release)"
fi
case "$OS_ID" in
  debian|ubuntu)
      NGINX_CONF_DIR=/etc/nginx/sites-available
      NGINX_ENABLE_DIR=/etc/nginx/sites-enabled
      sudo mkdir -p "$NGINX_CONF_DIR" "$NGINX_ENABLE_DIR"
      NGINX_CONF="$NGINX_CONF_DIR/club702"
      NGINX_ENLINK="$NGINX_ENABLE_DIR/club702"
      ;;
  centos|rhel|rocky|almalinux|fedora|anolis|alinux|alibaba)
      NGINX_CONF_DIR=/etc/nginx/conf.d
      NGINX_ENABLE_DIR=
      NGINX_CONF="$NGINX_CONF_DIR/club702.conf"
      NGINX_ENLINK=
      ;;
  *)
      warn "未能识别系统类型（os-release ID=$OS_ID），默认按 Debian 系处理（sites-available/sites-enabled）"
      NGINX_CONF_DIR=/etc/nginx/sites-available
      NGINX_ENABLE_DIR=/etc/nginx/sites-enabled
      sudo mkdir -p "$NGINX_CONF_DIR" "$NGINX_ENABLE_DIR"
      NGINX_CONF="$NGINX_CONF_DIR/club702"
      NGINX_ENLINK="$NGINX_ENABLE_DIR/club702"
      ;;
esac
info "Nginx 配置路径: $NGINX_CONF"

apply_template "$APP_DIR/deploy/nginx-club702.conf" "$NGINX_CONF" 644
# HTTPS 块：env.sh 提供 SSL_CERT_PATH/SSL_KEY_PATH 时保留（监听 443），否则删除（仅 HTTP 80）
if [[ -n "${SSL_CERT_PATH:-}" && -n "${SSL_KEY_PATH:-}" ]]; then
    sed -i 's|^[[:space:]]*@@HTTPS_BLOCK_START@@[[:space:]]*$||; s|^[[:space:]]*@@HTTPS_BLOCK_END@@[[:space:]]*$||' "$NGINX_CONF"
    ok "HTTPS 已启用：监听 443（证书: $SSL_CERT_PATH）"
else
    sed -i '/^[[:space:]]*@@HTTPS_BLOCK_START@@[[:space:]]*$/,/^[[:space:]]*@@HTTPS_BLOCK_END@@[[:space:]]*$/d' "$NGINX_CONF"
    warn "未配置 SSL_CERT_PATH/SSL_KEY_PATH，仅监听 HTTP 80"
fi
if [[ -n "$NGINX_ENLINK" && ! -e "$NGINX_ENLINK" ]]; then
    ln -s "$NGINX_CONF" "$NGINX_ENLINK"
fi
# 限流区必须定义在 http 上下文里，而站点配置（conf.d/*.conf、sites-enabled/*）
# 是包含在 http 块**内部**的，写不进去。所以由本脚本往 nginx.conf 追加一次定义
# （幂等：已有同名 zone 就跳过），站点配置里的 limit_req 引用它。
NGINX_MAIN_CONF="/etc/nginx/nginx.conf"
if [[ -f "$NGINX_MAIN_CONF" ]] && ! grep -q "zone=club702_login" "$NGINX_MAIN_CONF"; then
    info "向 nginx.conf 追加登录限流区"
    # 10m 共享内存约可容纳 16 万个 IP；登录是低频操作，够用很久。
    if sed -i "/^http {/a\    limit_req_zone \$binary_remote_addr zone=club702_login:10m rate=20r/m;" "$NGINX_MAIN_CONF"; then
        ok "已加入 limit_req_zone club702_login（20 次/分钟/IP）"
    else
        warn "追加 nginx.conf 失败，站点配置里的 limit_req 会因缺少 zone 而让 nginx -t 报错"
        warn "请手工在 nginx.conf 的 http 块内加入："
        warn "  limit_req_zone \$binary_remote_addr zone=club702_login:10m rate=20r/m;"
        exit 1
    fi
fi

if ! nginx -t >/dev/null 2>&1; then
    fail "Nginx 配置测试失败："
    nginx -t 2>&1 | sed "s/^/  /"
    exit 1
fi
systemctl reload nginx
ok "Nginx 配置已生效"

# ---------- 10. 健康检查 ----------
info "健康检查"
sleep 3
HTTP_CODE="$(curl -s -o /dev/null -w '%{http_code}' \
    -H "Host: $DEPLOY_PUBLIC_IP" \
    "http://${DJANGO_APP_HOST:-127.0.0.1}:${DJANGO_APP_PORT:-8000}/" || true)"
if [[ "$HTTP_CODE" == "200" ]]; then
    ok "应用健康检查通过 (HTTP $HTTP_CODE)"
else
    warn "健康检查未通过 (HTTP $HTTP_CODE)，请检查日志: journalctl -u club702 -n 50"
fi

cat <<EOF

${GRN}============================================${RST}
${GRN}  首次部署完成                              ${RST}
${GRN}============================================${RST}
  应用服务 : systemctl status club702
  备份定时 : systemctl list-timers | grep club702
  手动备份 : sudo -u ${DEPLOY_SYSTEM_USER} ${APP_DIR}/deploy/backup.sh
  备份位置 : ${DJANGO_BACKUP_DIR:-/var/backups/club702}（备份未加密时脚本会提醒）
  访问入口 : http://${DEPLOY_DOMAIN}/
  管理后台 : http://${DEPLOY_DOMAIN}/admin/
  日志     : journalctl -u club702 -f

  后续发布新版本: git checkout <新tag> 后执行 ./deploy/deploy.sh <新tag>
  说明        : 本脚本只负责首次部署；依赖环境的落地请参考 docs/deploy.md
EOF