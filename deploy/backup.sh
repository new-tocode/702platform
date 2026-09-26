#!/usr/bin/env bash
# 每日备份脚本 —— 由 systemd (club702-backup.timer) 触发，也可手动执行。
# 手动执行: sudo -u <DEPLOY_SYSTEM_USER> ./deploy/backup.sh
# 备份内容: PostgreSQL 数据库 + 两个上传目录（公开的 mediafiles/ 与受保护的
#           protected_media/），保留份数由 env.sh 的 DJANGO_BACKUP_RETAIN 控制。
#
# 备份里是实名身份、学号手机号与全部评审意见，比在线库更集中。两条相关配置：
#   DJANGO_BACKUP_DIR    备份落盘位置。**推荐 /var/backups/club702**（本平台线上用的
#                        就是它）：systemd 给应用进程整个 APP_DIR 的写权限
#                        （ReadWritePaths），备份留在应用目录里意味着**被攻陷的 Web
#                        应用能删改备份**——而备份的意义正是「数据被改了还能回到从前」。
#                        外置目录不在 ReadWritePaths 里，应用进程碰不到它。
#                        （只防应用进程，不防拿到部署用户 Shell 的人；那种情况要靠
#                        异地副本，见文件末尾。）留空则退回 $APP_DIR/backups。
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

# 备份目录。默认在应用目录内（$APP_DIR/backups）——这是部署现实决定的：外置目录
# 通常属 root，而部署脚本没有提权，硬默认到外面会让第一次运行就失败。
#
# 想搬到应用之外（更安全：应用被攻陷或主机被勒索时，备份不会与数据一起没）：
#   sudo mkdir -p /var/backups/club702 && sudo chown <部署用户> /var/backups/club702
# 然后在 env.sh 里设 DJANGO_BACKUP_DIR=/var/backups/club702。
#
# **本脚本的兜底值是应用目录内，与 install.sh / env.template 的推荐值不同**——
# 这是有意的：本脚本由 systemd timer 每天自动调用，一旦兜底值指向一个尚未创建的
# 外置目录，备份会**直接失败**（那比备份在应用内更糟）。所以新部署由 install.sh
# 把目录建好、由 env.template 把路径写进 env.sh；老部署保持原样，不会因为升级
# 脚本而突然备不了份。
BACKUP_DIR="${DJANGO_BACKUP_DIR:-$APP_DIR/backups}"
if ! mkdir -p "$BACKUP_DIR" 2>/dev/null; then
    echo "备份目录 $BACKUP_DIR 不存在且创建失败。" >&2
    echo "" >&2
    echo "外置目录（如 /var/backups/club702）的父目录通常属 root，部署用户建不出来，需要先用有 sudo 的账号执行一次：" >&2
    echo "  sudo mkdir -p $BACKUP_DIR" >&2
    echo "  sudo chown $(id -un) $BACKUP_DIR" >&2
    echo "  sudo chmod 700 $BACKUP_DIR" >&2
    echo "" >&2
    echo "若只是想备份在应用目录里，把 env.sh 的 DJANGO_BACKUP_DIR 留空即可。" >&2
    exit 1
fi
if [[ ! -w "$BACKUP_DIR" ]]; then
    echo "备份目录 $BACKUP_DIR 不可写，请检查属主与权限。" >&2
    exit 1
fi

# 收紧备份目录权限。备份里是成员姓名、学号手机号、密码散列与全部评审意见，
# 而家目录与子目录默认是 755——系统上任何账号都能一路穿越进来读走。
# 700 只留属主（= 部署用户，也是恢复时用的那个账号）可进可读。
if [[ "$(stat -c '%a' "$BACKUP_DIR")" != "700" ]]; then
    chmod 700 "$BACKUP_DIR" 2>/dev/null || {
        echo "  !! 无法收紧 $BACKUP_DIR 的权限（属主不是 $(id -un)？）" >&2
        echo "     请用有 sudo 的账号执行: sudo chown $(id -un) $BACKUP_DIR && sudo chmod 700 $BACKUP_DIR" >&2
    }
fi

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

SUF="$(suffix)"

# 收紧备份文件权限。gzip/tar 按 umask 创建（常见 644 = 同机所有账号可读）；
# 顺带把目录里已有的历史备份一并收紧——它们不该因为「那时还没加这一步」而一直敞着。
chmod 600 "$BACKUP_DIR"/db-*.sql.gz"$SUF" "$BACKUP_DIR"/media-*.tar.gz"$SUF" 2>/dev/null || true

# 按保留份数清理旧的 db 与 media 备份（各自独立保留 RETAIN 份）
ls -1t "$BACKUP_DIR"/db-*.sql.gz"$SUF"    2>/dev/null | tail -n +$((RETAIN + 1)) | xargs -r rm --
ls -1t "$BACKUP_DIR"/media-*.tar.gz"$SUF" 2>/dev/null | tail -n +$((RETAIN + 1)) | xargs -r rm --

echo "[$(date '+%F %T')] 备份完成: $BACKUP_DIR/db-$STAMP.sql.gz$SUF $BACKUP_DIR/media-$STAMP.tar.gz$SUF"

# 两条提醒按「当下能不能被利用」排序：权限是本机账号立刻就能读走，
# 加密防的是备份文件离开这台机器之后被读（要先有异地副本才有意义）。
if [[ "$(stat -c '%a' "$BACKUP_DIR")" != "700" ]]; then
    echo "  !! 备份目录权限是 $(stat -c '%a' "$BACKUP_DIR")，同机其它账号可能读到备份内容。"
    echo "     请执行: chmod 700 $BACKUP_DIR"
fi
if [[ -z "${DJANGO_BACKUP_GPG_RECIPIENT:-}" ]]; then
    echo "  !! 备份未加密。里面有成员姓名、学号手机号与全部评审意见——若备份要离开这台"
    echo "     机器（异地副本、交给别人），先配置 DJANGO_BACKUP_GPG_RECIPIENT 再传。"
fi

# 异地备份建议（可选）：把备份目录同步到另一台机器或对象存储，例如
# rsync -az "$BACKUP_DIR/" backup-user@backup-host:/path/
# 本机备份挡不住主机级故障（磁盘损坏、误删、勒索），异地那份才是最后一道。