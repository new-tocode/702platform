#!/usr/bin/env bash
# 每日备份脚本 —— 由 root 的 cron 调用:  30 3 * * * /opt/702platform/deploy/backup.sh
# 备份 PostgreSQL 数据库与上传媒体，保留 14 份。
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/702platform}"

cd "$APP_DIR"
# 读取 DJANGO_DB_* 变量
# shellcheck disable=SC1091
source env.sh

mkdir -p backups
STAMP="$(date +%F-%H%M)"

pg_dump --username "$DJANGO_DB_USER" --host "${DJANGO_DB_HOST:-127.0.0.1}" \
    "$DJANGO_DB_NAME" | gzip > "backups/db-daily-$STAMP.sql.gz"
tar -czf "backups/media-daily-$STAMP.tar.gz" mediafiles/

# 保留最近 14 份
ls -1t backups/db-daily-*.sql.gz | tail -n +15 | xargs -r rm --
ls -1t backups/media-daily-*.tar.gz | tail -n +15 | xargs -r rm --

# 建议额外把 backups/ 同步到异地（rsync/对象存储），此处留接口:
# rsync -az backups/ backup-user@backup-host:/path/to/702platform-backups/
