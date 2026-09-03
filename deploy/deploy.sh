#!/usr/bin/env bash
# 生产发布脚本 —— 更新到某个 git tag 的流程。
# 用法: sudo -u <DEPLOY_SYSTEM_USER> ./deploy/deploy.sh <tag>   例如: ./deploy/deploy.sh v1.0.1
# 约定: 服务器代码只从 git tag 取；任何 migrate 之前先备份。
# 首次部署请用 ./deploy/install.sh，本脚本只处理"已有环境"下的版本更新。
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"
SERVICE_NAME="club702"

if [ "$#" -ne 1 ]; then
    echo "用法: $0 <git-tag>   例如: $0 v1.0.1" >&2
    exit 1
fi
TAG="$1"

set -a
# shellcheck disable=SC1090
source env.sh
set +a

APP_HOST="${DJANGO_APP_HOST:-127.0.0.1}"
APP_PORT="${DJANGO_APP_PORT:-8000}"
SITE_URL="http://${APP_HOST}:${APP_PORT}"

# 必须以部署用户（DEPLOY_SYSTEM_USER）运行，避免污染 root 属主
DEPLOY_USER="${DEPLOY_SYSTEM_USER:-}"
if [[ -n "$DEPLOY_USER" ]] && [[ "$(id -u)" -eq 0 ]] && [[ "$(id -un)" != "$DEPLOY_USER" ]]; then
    exec sudo -u "$DEPLOY_USER" bash "$0" "$TAG"
fi

echo "==> 1/5 备份数据库和媒体（分别保留 ${DJANGO_BACKUP_RETAIN:-14} 份）"
mkdir -p backups
STAMP="$(date +%F-%H%M)"
case "${DJANGO_DB_ENGINE:-django.db.backends.postgresql}" in
  *postgres*)
    PGPASSWORD="$DJANGO_DB_PASSWORD" pg_dump \
        --username "$DJANGO_DB_USER" \
        --host "${DJANGO_DB_HOST:-127.0.0.1}" \
        --port "${DJANGO_DB_PORT:-5432}" \
        "$DJANGO_DB_NAME" | gzip > "backups/db-$STAMP.sql.gz"
    ;;
  *) echo "    跳过数据库备份（非 PostgreSQL 引擎）";;
esac
tar -czf "backups/media-$STAMP.tar.gz" mediafiles/
RETAIN="${DJANGO_BACKUP_RETAIN:-14}"
ls -1t backups/db-*.sql.gz    2>/dev/null | tail -n +$((RETAIN + 1)) | xargs -r rm --
ls -1t backups/media-*.tar.gz 2>/dev/null | tail -n +$((RETAIN + 1)) | xargs -r rm --
echo "    备份完成: backups/db-$STAMP.sql.gz"

echo "==> 2/5 切换版本 $TAG"
git fetch --tags origin
git checkout "$TAG"

echo "==> 3/5 安装/更新依赖"
.venv/bin/python -m pip install --quiet -r requirements.txt -r requirements-prod.txt

echo "==> 4/5 数据库迁移 + 静态文件"
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py collectstatic --noinput

echo "==> 5/5 重启服务 + 健康检查"
systemctl restart "$SERVICE_NAME"
sleep 2
if curl -fsS "$SITE_URL" > /dev/null; then
    echo "✅ 上线成功: $TAG"
else
    echo "❌ 健康检查失败，请立即检查: journalctl -u $SERVICE_NAME -n 50" >&2
    echo "   回滚: git checkout <上一个tag> && ./deploy/deploy.sh <上一个tag>" >&2
    exit 1
fi