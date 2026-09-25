#!/usr/bin/env bash
# 每日备份脚本 —— 由 systemd (club702-backup.timer) 触发，也可手动执行。
# 手动执行: sudo -u <DEPLOY_SYSTEM_USER> ./deploy/backup.sh
# 备份内容: PostgreSQL 数据库 + 两个上传目录（公开的 mediafiles/ 与受保护的
#           protected_media/），保留份数由 env.sh 的 DJANGO_BACKUP_RETAIN 控制。
#
# 备份里是实名身份、学号手机号与全部评审意见，比在线库更集中。两条相关配置：
#   DJANGO_BACKUP_DIR    备份落盘位置。**默认放在应用目录之外**——应用进程对整个
#                        APP_DIR 有写权限（systemd 的 ReadWritePaths），备份留在里面
#                        意味着应用一旦被攻陷、或者主机被勒索，备份与数据一起没了。
#   DJANGO_BACKUP_GPG_RECIPIENT
#                        给了就加密（gpg 公钥），不给就明文并打印提醒。
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

# 备份目录默认在应用目录**之外**。留在 APP_DIR 里的话，应用进程（systemd 给了
# 整个 APP_DIR 的写权限）与任何拿到该账号的人都能改掉备份——备份的意义正是
# 「数据被改了还能回到从前」，它不该和它保护的东西住在一起。
BACKUP_DIR="${DJANGO_BACKUP_DIR:-/var/backups/club702}"
mkdir -p "$BACKUP_DIR"
STAMP="$(date +%F-%H%M)"
RETAIN="${DJANGO_BACKUP_RETAIN:-14}"

# 加密：给了收件人就用它，否则明文并在结尾提醒。备份不该以明文长期躺在磁盘上。
encrypt() {
    if [[ -n "${DJANGO_BACKUP_GPG_RECIPIENT:-}" ]]; then
        gpg --batch --yes --encrypt --recipient "$DJANGO_BACKUP_GPG_RECIPIENT" -o "$1.gpg" && rm -f "$1"
    else
        return 0
    fi
}
suffix() { [[ -n "${DJANGO_BACKUP_GPG_RECIPIENT:-}" ]] && echo ".gpg" || echo ""; }

# 数据库与媒体分两步导出，不是同一时间点的快照：恢复后可能出现「库里有记录、
# 媒体文件缺失」或反之。社团规模下这个窗口（秒级）可以接受；要严格一致就先停写。
PGPASSWORD="$DJANGO_DB_PASSWORD" pg_dump \
    --username "$DJANGO_DB_USER" \
    --host "${DJANGO_DB_HOST:-127.0.0.1}" \
    --port "${DJANGO_DB_PORT:-5432}" \
    "$DJANGO_DB_NAME" | gzip > "$BACKUP_DIR/db-$STAMP.sql.gz"
encrypt "$BACKUP_DIR/db-$STAMP.sql.gz"

# 两个上传目录都要备份：mediafiles/ 是公开的媒体库配图，protected_media/ 是
# 项目书、批注版、头像、图册这些受保护的文件（它们刻意不在 mediafiles/ 之下，
# 所以只打包前者会把它们整批漏掉）。目录可能还不存在，缺一个就跳过那一个。
tar -czf "$BACKUP_DIR/media-$STAMP.tar.gz" \
    $( [ -d mediafiles ] && echo mediafiles/ ) \
    $( [ -d protected_media ] && echo protected_media/ )
encrypt "$BACKUP_DIR/media-$STAMP.tar.gz"

# 按保留份数清理旧的 db 与 media 备份（各自独立保留 RETAIN 份）
SUF="$(suffix)"
ls -1t "$BACKUP_DIR"/db-*.sql.gz"$SUF"    2>/dev/null | tail -n +$((RETAIN + 1)) | xargs -r rm --
ls -1t "$BACKUP_DIR"/media-*.tar.gz"$SUF" 2>/dev/null | tail -n +$((RETAIN + 1)) | xargs -r rm --

echo "[$(date '+%F %T')] 备份完成: $BACKUP_DIR/db-$STAMP.sql.gz$SUF $BACKUP_DIR/media-$STAMP.tar.gz$SUF"

if [[ -z "${DJANGO_BACKUP_GPG_RECIPIENT:-}" ]]; then
    echo "  !! 备份未加密。里面是实名身份与全部评审意见，建议配置 DJANGO_BACKUP_GPG_RECIPIENT。"
fi

# 异地备份建议（可选）：把备份目录同步到另一台机器或对象存储，例如
# rsync -az "$BACKUP_DIR/" backup-user@backup-host:/path/
# 本机备份挡不住主机级故障（磁盘损坏、误删、勒索），异地那份才是最后一道。