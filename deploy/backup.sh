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
#
# 加密那行有两处**不能省**，都是踩出来的：
#
# 1) 末尾的 "$1" 是输入文件。gpg 少了它就去读 stdin，而 systemd 下 stdin 是 /dev/null：
#    它「成功」加密了一段空内容（退出码 0），紧接着的 rm -f 把真正的明文备份删掉——
#    留下的是一份能解密、解出来却是空的 .gpg，真备份没了。**加密开关一打开就生效**，
#    且整轮备份还报「完成」。改这一行时别把最后的 "$1" 当多余参数删掉。
# 2) --trust-model always：生产机上按纪律只放公钥（私钥留在备份机），而别处导入的公钥
#    在本机信任模型里是 untrusted。交互式 gpg 这时会问一句「still use this key?」，本
#    脚本带 --batch，问不出来就成了硬失败（no assurance this key belongs to the named
#    user），set -e 之下这一轮备份当场中断，只在 journal 里留一行。另一条路是导入后把
#    公钥标成 ultimate trust，但那要靠一次手工步骤，trustdb 一丢就变成**每天静默失败**
#    ——对无人值守的备份，写死在命令里更牢靠。
#
# 收件人是管理员在 env.sh 里写死的、不是外部输入，跳过信任检查不引入新的攻击面。用它有
# 两点代价要认：
#   · **收件人填完整指纹，别填邮箱或裸名字**。gpg 的 -r 是子串匹配：写成 club702 这种宽
#     名字时它会**静默**挑中一把（退出码 0、不报歧义），挑错了就等于加密给一个解不开的
#     人——而这条静默路径正是 --trust-model always 关掉「收件人不可信」那道硬失败后放行的。
#   · --trust-model always **不豁免有效期**：公钥过期或被吊销仍是硬失败。这条是响亮的，
#     可以接受，但别以为加了它就再不会因收件人失败。
#
# 私钥要留在备份机而不是生产机上——那条纪律见 docs/更新维护/开发与部署.md §5。
encrypt() {
    if [[ -n "${DJANGO_BACKUP_GPG_RECIPIENT:-}" ]]; then
        gpg --batch --yes --trust-model always --encrypt \
            --recipient "$DJANGO_BACKUP_GPG_RECIPIENT" -o "$1.gpg" "$1" && rm -f "$1"
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

# 目录里同一类产物可能有两代：明文（加密关时产出）与 .gpg（加密开时产出）。**收紧权限与
# 清理都要按两代一起收**，不能只按当前的 $SUF：只收一代的后果是另一代既不被 chmod、也不
# 受 RETAIN 约束——于是某次把加密开关一拨，此前攒下的那批明文备份就永远留在盘上，正是
# 加密要防的东西。两类一起数还顺带避免了「开关切换后两代各留 RETAIN 份」的加倍占用。
#
# 用函数列出**实际存在**的文件，而不是把两个通配符直接交给 ls：通配符不匹配时 bash 会把
# 它原样传给 ls，ls 报错退出 2，而本脚本带 pipefail——那条管道失败会让整轮备份在清理这
# 一步中止（备份其实已经做完了）。
backups_of() {  # $1 = db 或 media
    local f
    for f in "$BACKUP_DIR/$1-"*.gz "$BACKUP_DIR/$1-"*.gz.gpg; do
        [[ -e "$f" ]] && printf '%s\n' "$f"
    done
}

# 按保留份数清理旧的 db 与 media 备份（各自独立保留 RETAIN 份）
prune() {
    local files=()
    mapfile -t files < <(backups_of "$1")
    [[ ${#files[@]} -gt 0 ]] || return 0
    # 刚写出的那几份也要一并收紧权限：gzip/tar 按 umask 创建（常见 644 = 同机所有账号
    # 可读），目录里更早的历史备份同样不该因为「那时还没加这一步」而一直敞着。
    chmod 600 "${files[@]}" 2>/dev/null || true
    ls -1t "${files[@]}" | tail -n +$((RETAIN + 1)) | xargs -r rm --
}
prune db
prune media

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