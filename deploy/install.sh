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
    fail "首次运行，已从模板创建 $ENV_FILE"
    fail "请编辑该文件，把所有 <尖括号> 占位符替换为真实值后重新运行本脚本"
    exit 1
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
for var in DJANGO_SECRET_KEY DJANGO_ALLOWED_HOSTS DJANGO_DB_ENGINE DJANGO_DB_NAME \
           DJANGO_DB_USER DJANGO_DB_PASSWORD DJANGO_SUPERUSER_USERNAME \
           DJANGO_SUPERUSER_EMAIL DJANGO_SUPERUSER_PASSWORD \
           DEPLOY_SERVER_NAME DEPLOY_SYSTEM_USER DJANGO_BACKUP_SCHEDULE; do
    if [[ -z "${!var:-}" ]]; then
        fail "env.sh 缺少必需配置项 $var（请参照 deploy/env.template）"
        exit 1
    fi
done

# ---------- 3. 依赖环境检测（只提示，不自动安装） ----------
MISSING=()
need_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        MISSING+=("缺少系统命令 $1（$2）")
    fi
}
need_cmd python3        "如 Ubuntu: sudo apt install python3 python3-venv"
need_cmd systemctl      "systemd 未启用，本部署依赖 systemd"
need_cmd nginx          "如 Ubuntu: sudo apt install nginx"
need_cmd psql           "PostgreSQL 客户端，如 Ubuntu: sudo apt install postgresql-client"
need_cmd pg_isready     "PostgreSQL 客户端工具，如 Ubuntu: sudo apt install postgresql-client"
need_cmd sudo           "本脚本需要 sudo 权限"

# PostgreSQL 服务本身
need_cmd postgres       "PostgreSQL 服务端未安装，如 Ubuntu: sudo apt install postgresql"

# Python 版本 >= 3.10
if command -v python3 >/dev/null 2>&1; then
    PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
        MISSING+=("Python 版本过低($PY_VER)，需要 >= 3.10")
    fi
fi

# 项目虚拟环境与依赖（不自动 pip install，只检测）
if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
    MISSING+=("缺少虚拟环境 $APP_DIR/.venv（请先执行: python3 -m venv .venv）")
fi
for pkg in Django rest_framework bleach markdown PIL psycopg gunicorn; do
    if ! "$APP_DIR/.venv/bin/python" -c "import $pkg" >/dev/null 2>&1; then
        MISSING+=("Python 依赖未安装: $pkg（请先执行: $APP_DIR/.venv/bin/python -m pip install -r requirements.txt -r requirements-prod.txt）")
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

# ---------- 4. 数据库就绪（默认 PostgreSQL） ----------
case "$DJANGO_DB_ENGINE" in
  *postgres*)
    info "确保 PostgreSQL 服务运行中"
    if ! systemctl is-active postgresql >/dev/null 2>&1; then
        systemctl start postgresql || true
    fi

    info "确保数据库角色 $DJANGO_DB_USER 存在"
    if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DJANGO_DB_USER'" | grep -q 1; then
        # CREATEDB: 允许 Django 测试(`manage.py test`)创建临时测试库
        sudo -u postgres psql -c "CREATE ROLE \"$DJANGO_DB_USER\" LOGIN CREATEDB PASSWORD '$DJANGO_DB_PASSWORD'"
        ok "已创建数据库角色 $DJANGO_DB_USER"
    else
        info "数据库角色 $DJANGO_DB_USER 已存在，跳过"
    fi

    info "确保数据库 $DJANGO_DB_NAME 存在"
    if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DJANGO_DB_NAME'" | grep -q 1; then
        sudo -u postgres createdb -O "$DJANGO_DB_USER" "$DJANGO_DB_NAME"
        ok "已创建数据库 $DJANGO_DB_NAME"
    else
        info "数据库 $DJANGO_DB_NAME 已存在，跳过"
    fi
    ;;
  *sqlite*)
    warn "使用 SQLite（仅建议轻量测试），跳过数据库账号创建"
    ;;
  *)
    fail "不支持的 DJANGO_DB_ENGINE: $DJANGO_DB_ENGINE"
    exit 1
    ;;
esac

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

# ---------- 7. collectstatic ----------
info "收集静态文件"
run_as_app .venv/bin/python manage.py collectstatic --noinput >/dev/null
ok "静态文件已收集到 staticfiles/"

# ---------- 8. 注册 systemd 服务 ----------
info "注册 systemd 服务与备份定时器"

RENDER=(
    -e "s|@@APP_DIR@@|$APP_DIR|g"
    -e "s|@@APP_USER@@|$DEPLOY_SYSTEM_USER|g"
    -e "s|@@APP_HOST@@|$DJANGO_APP_HOST|g"
    -e "s|@@APP_PORT@@|$DJANGO_APP_PORT|g"
    -e "s|@@SERVER_NAME@@|$DEPLOY_SERVER_NAME|g"
    -e "s|@@BACKUP_SCHEDULE@@|$DJANGO_BACKUP_SCHEDULE|g"
    -e "s|@@BACKUP_RETAIN@@|$DJANGO_BACKUP_RETAIN|g"
    -e "s|@@VENV@@|$APP_DIR/.venv|g"
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

# ---------- 9. 配置 Nginx ----------
info "配置 Nginx"
apply_template "$APP_DIR/deploy/nginx-club702.conf" "/etc/nginx/sites-available/club702" 644
if [[ ! -e "/etc/nginx/sites-enabled/club702" ]]; then
    ln -s /etc/nginx/sites-available/club702 /etc/nginx/sites-enabled/club702
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
    -H "Host: $DEPLOY_SERVER_NAME" \
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
  手动备份 : /opt 下执行 backups/ 相关脚本
  访问入口 : http://${DEPLOY_SERVER_NAME}/
  管理后台 : http://${DEPLOY_SERVER_NAME}/admin/
  日志     : journalctl -u club702 -f

  后续发布新版本: git checkout <新tag> 后执行 ./deploy/deploy.sh <新tag>
  说明        : 本脚本只负责首次部署；依赖环境的落地请参考 docs/deploy-production.md
EOF