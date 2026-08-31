#!/usr/bin/env bash
# 生产发布脚本 —— 首次部署与每次更新走同一套流程。
# 用法: ./deploy/deploy.sh <tag>        例如: ./deploy/deploy.sh v1.0.1
# 约定: 服务器代码只从 git tag 取；任何 migrate 之前先备份。
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/702platform}"
SERVICE_NAME="${SERVICE_NAME:-club702}"
SITE_URL="${SITE_URL:-http://127.0.0.1:8000}"

if [ "$#" -ne 1 ]; then
    echo "用法: $0 <git-tag>   例如: $0 v1.0.1" >&2
    exit 1
fi
TAG="$1"

cd "$APP_DIR"
# shellcheck disable=SC1091
source env.sh

echo "==> 1/6 备份数据库和媒体（backups/ 下保留最近若干份）"
mkdir -p backups
STAMP="$(date +%F-%H%M)"
pg_dump --username "$DJANGO_DB_USER" --host "${DJANGO_DB_HOST:-127.0.0.1}" \
    "$DJANGO_DB_NAME" | gzip > "backups/db-$STAMP.sql.gz"
tar -czf "backups/media-$STAMP.tar.gz" mediafiles/
# 只保留最近 14 份备份
ls -1t backups/db-*.sql.gz | tail -n +15 | xargs -r rm --
ls -1t backups/media-*.tar.gz | tail -n +15 | xargs -r rm --
echo "    备份完成: backups/db-$STAMP.sql.gz"

echo "==> 2/6 切换版本 $TAG"
git fetch --tags origin
git checkout "$TAG"

echo "==> 3/6 安装/更新依赖"
.venv/bin/python -m pip install --quiet -r requirements.txt -r requirements-prod.txt

echo "==> 4/6 服务器上跑全量测试（临时测试库，不触碰生产数据）"
.venv/bin/python manage.py test --verbosity 1

echo "==> 5/6 数据库迁移 + 静态文件"
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py collectstatic --noinput

echo "==> 6/6 重启服务 + 健康检查"
sudo systemctl restart "$SERVICE_NAME"
sleep 2
if curl -fsS "$SITE_URL" > /dev/null; then
    echo "✅ 上线成功: $TAG"
else
    echo "❌ 健康检查失败，请立即检查: journalctl -u $SERVICE_NAME -n 50" >&2
    echo "   回滚: git checkout <上一个tag> && sudo systemctl restart $SERVICE_NAME" >&2
    exit 1
fi
