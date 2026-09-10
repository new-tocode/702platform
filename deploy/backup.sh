#!/usr/bin/env bash
# 每日备份脚本 —— 由 systemd (club702-backup.timer) 触发，也可手动执行。
# 手动执行: sudo -u <DEPLOY_SYSTEM_USER> ./deploy/backup.sh
# 备份内容: PostgreSQL 数据库 + 上传媒体目录，保留份数由 env.sh 的 DJANGO_BACKUP_RETAIN 控制。
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

# 读取 DJANGO_DB_* 等配置
set -a
# shellcheck disable=SC1090
source env.sh
set +a

# pg_dump 不一定在默认 PATH：RHEL/PGDG 装在 /usr/pgsql-<ver>/bin，而 systemd 触发
# 本脚本时用的是系统默认 PATH（不含该目录）。这里自动探测并前置，保证备份可用。
if ! command -v pg_dump >/dev/null 2>&1; then
    # shellcheck disable=SC2046
    for d in $(ls -d /usr/pgsql-*/bin /usr/lib/postgresql/*/bin /usr/local/pgsql/bin /opt/pgsql*/bin 2>/dev/null | sort -rV); do
        if [[ -x "$d/pg_dump" ]]; then
            export PATH="$d:$PATH"
            break
        fi
    done
fi

mkdir -p backups
STAMP="$(date +%F-%H%M)"
RETAIN="${DJANGO_BACKUP_RETAIN:-14}"

case "${DJANGO_DB_ENGINE:-django.db.backends.postgresql}" in
  *postgres*)
    PGPASSWORD="$DJANGO_DB_PASSWORD" pg_dump \
        --username "$DJANGO_DB_USER" \
        --host "${DJANGO_DB_HOST:-127.0.0.1}" \
        --port "${DJANGO_DB_PORT:-5432}" \
        "$DJANGO_DB_NAME" | gzip > "backups/db-$STAMP.sql.gz"
    ;;
  *)
    echo "跳过数据库备份（非 PostgreSQL 引擎）" >&2
    ;;
esac

tar -czf "backups/media-$STAMP.tar.gz" mediafiles/

# 按保留份数清理旧的 db 与 media 备份（各自独立保留 RETAIN 份）
ls -1t backups/db-*.sql.gz  2>/dev/null | tail -n +$((RETAIN + 1)) | xargs -r rm --
ls -1t backups/media-*.tar.gz 2>/dev/null | tail -n +$((RETAIN + 1)) | xargs -r rm --

echo "[$(date '+%F %T')] 备份完成: backups/db-$STAMP.sql.gz backups/media-$STAMP.tar.gz"

# 异地备份建议（可选）：把 backups/ 同步到另一台机器或对象存储，例如
# rsync -az backups/ backup-user@backup-host:/path/