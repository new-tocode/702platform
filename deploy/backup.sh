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

# 新建文件一律 600、目录 700 起。备份里是实名身份、学号手机号与全部评审意见，而默认
# umask（常见 022）会让 gzip / tar / gpg 刚写出的那份先是 644——脚本末尾虽然会 chmod 600，
# 但中途一失败（磁盘满、加密报错）就轮不到那一步，明文库导出就那样敞在同机其它账号眼前。
# 目录权限是第二道（BACKUP_DIR 另按 700 收紧），而它收紧失败时只提醒、不退出，所以先在这里
# 把默认值立好，别把安全性押在末尾那一次 chmod 上。
umask 077

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

# 同一分钟里可能有两个 run 同时在跑：timer 到点、deploy.sh 的第 1/6 步、运维手工，各算一次。
# 它们会写同名文件（时间戳只到分钟）并互相覆盖与删除，最坏的结果是这一分钟一个备份都不剩。
# 这里用一把排他锁把「同一时刻只跑一个」变成硬保证：第二个进来的说明情况后直接退出——
# 退出码是 0，因为它没出错，只是没必要再跑一遍。
#
# 锁内顺手清掉上一轮被 kill 留下的 .part（「写了一半」的东西，不该留在目录里冒充备份、
# 也不该被保留份数算进去）。此刻持有锁，所以不会误删另一个 run 正在写的那一份。
LOCK_FILE="$BACKUP_DIR/.lock"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "[$(date '+%F %T')] 另一次备份正在进行（锁 $LOCK_FILE），本次跳过。" >&2
    exit 0
fi
find "$BACKUP_DIR" -maxdepth 1 -name '*.part' -delete 2>/dev/null || true

STAMP="$(date +%F-%H%M)"
RETAIN="${DJANGO_BACKUP_RETAIN:-14}"
# 保留份数必须是正整数。0（很容易被读成「不限制」）、负数或非数字都会让下面的挑拣从第一份
# 就开始删——**把刚做好的备份连同全部历史一起删光，而脚本照旧打印「备份完成」、以 0 退出**。
# 配置里错一个值就能静默毁掉所有备份，所以拦一道，退回默认 14 份。（非数字原本还会以
# 「unbound variable」中止在算术展开上，同样在这里一并解决。）
if [[ ! "$RETAIN" =~ ^[1-9][0-9]*$ ]]; then
    echo "  !! DJANGO_BACKUP_RETAIN 必须是正整数（当前是 '$RETAIN'），本次按 14 份保留。" >&2
    RETAIN=14
fi

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
#
# 加密之后**不做内容校验**，因为在这台机器上做不到：密文只有收件人能解，生产机上只有公钥，
# 连 gpg --list-packets 都会因缺私钥退出 2——照它判好坏会把好密文一起判成坏的，加密就等于
# 永远不生效。能做的兜底是上面那条 "$1"、下面「失败即删残片」，以及让失败响亮。
encrypt() {
    [[ -n "${DJANGO_BACKUP_GPG_RECIPIENT:-}" ]] || return 0
    # 写 .part、成功才改名上位，失败时删掉的**一定是本次自己写的半成品**。直接写 "$1.gpg"
    # 再在失败时删它是不行的：时间戳只到分钟，同一分钟里另一个 run（timer 与手工、或
    # deploy.sh 的第 1/6 步）可能已经写好同名成品，那样删掉的是**别人的有效密文**——这一
    # 分钟就一个备份都不剩，而成功的那轮早已打印过「备份完成」。
    if ! gpg --batch --yes --trust-model always --encrypt \
             --recipient "$DJANGO_BACKUP_GPG_RECIPIENT" -o "$1.gpg.part" "$1"; then
        rm -f "$1.gpg.part"
        echo "  !! 加密失败：已删掉残缺的密文、保留明文 $1" >&2
        echo "     收件人 $DJANGO_BACKUP_GPG_RECIPIENT 的公钥还在部署用户的钥匙串里吗？" >&2
        return 1
    fi
    mv -f "$1.gpg.part" "$1.gpg"
    rm -f "$1"
}
suffix() { [[ -n "${DJANGO_BACKUP_GPG_RECIPIENT:-}" ]] && echo ".gpg" || echo ""; }

# 加密开启时产物名多一个 .gpg 后缀。**先算出来**：下面的产出清单要用它，而 set -u 会让
# 「先用后定义」当场失败（这里踩过一次）。
SUF="$(suffix)"

# 数据库与媒体分两步导出，不是同一时间点的快照：恢复后可能出现「库里有记录、
# 媒体文件缺失」或反之。社团规模下这个窗口（秒级）可以接受；要严格一致就先停写。
# 库导出与媒体打包同样先写 .part、成功才改名：磁盘满或 pg_dump/tar 中途报错会留下**半截
# 的明文**（db-*.sql.gz、media-*.tar.gz）。它按 mtime 算「最新」，于是顶掉一个保留名额、
# 把较旧的有效备份挤走；库那份还会让 deploy.sh 的体检报「✅ 最近一份数据库备份在 0 小时
# 前」——假绿。半截的东西连解都解不开，处置与「加密失败时保留的明文」（那是完整可用的
# 备份）正相反：必须清掉。
DB_PLAIN="$BACKUP_DIR/db-$STAMP.sql.gz"
if ! PGPASSWORD="$DJANGO_DB_PASSWORD" pg_dump \
        --username "$DJANGO_DB_USER" \
        --host "${DJANGO_DB_HOST:-127.0.0.1}" \
        --port "${DJANGO_DB_PORT:-5432}" \
        "$DJANGO_DB_NAME" | gzip > "$DB_PLAIN.part"; then
    rm -f "$DB_PLAIN.part"
    echo "  !! 数据库导出失败（磁盘满？连接断了？）：已清掉半成品，本次没有库备份。" >&2
    exit 1
fi
mv -f "$DB_PLAIN.part" "$DB_PLAIN"
encrypt "$DB_PLAIN"
# 结尾只报**真正产出**的那几份：媒体那一步可能整段跳过（两个目录都没有），把不存在的
# 文件写进「备份完成」，读日志的人会以为媒体也备好了。
PRODUCED=("$DB_PLAIN$SUF")

# 两个上传目录都要备份：mediafiles/ 是公开的媒体库配图，protected_media/ 是
# 项目书、批注版、头像、图册这些受保护的文件（它们刻意不在 mediafiles/ 之下，
# 所以只打包前者会把它们整批漏掉）。目录可能还不存在，缺一个就跳过那一个。
MEDIA_SOURCES=()
if [[ -d mediafiles ]]; then MEDIA_SOURCES+=(mediafiles/); fi
if [[ -d protected_media ]]; then MEDIA_SOURCES+=(protected_media/); fi
MEDIA_PLAIN="$BACKUP_DIR/media-$STAMP.tar.gz"
if [[ ${#MEDIA_SOURCES[@]} -gt 0 ]]; then
    if ! tar -czf "$MEDIA_PLAIN.part" "${MEDIA_SOURCES[@]}"; then
        rm -f "$MEDIA_PLAIN.part"
        echo "  !! 媒体打包失败（某个上传件读不了？磁盘满？）：已清掉半成品。" >&2
        exit 1
    fi
    mv -f "$MEDIA_PLAIN.part" "$MEDIA_PLAIN"
    encrypt "$MEDIA_PLAIN"
    PRODUCED+=("$MEDIA_PLAIN$SUF")
else
    # 两个目录都没有时，别照旧把空清单交给 tar：它会以「Cowardly refusing to create an
    # empty archive」退出 2，set -e 之下整轮备份就此中止——库明明已经备好了，却报成失败。
    echo "  跳过媒体备份：mediafiles/ 与 protected_media/ 都不存在" >&2
fi

# 目录里同一类产物可能有两代：明文（加密关时产出）与 .gpg（加密开时产出）。**收紧权限与
# 清理都要按两代一起收**，不能只按当前的 $SUF：只收一代的后果是另一代既不被 chmod、也不
# 受 RETAIN 约束——于是某次把加密开关一拨，此前攒下的那批明文备份就永远留在盘上，正是
# 加密要防的东西。两类一起数还顺带避免了「开关切换后两代各留 RETAIN 份」的加倍占用。
#
# 用函数列出**实际存在**的文件，而不是把两个通配符直接交给 ls：通配符不匹配时 bash 会把
# 它原样传给 ls，ls 报错退出 2，而本脚本带 pipefail——那条管道失败会让整轮备份在清理这
# 一步中止（备份其实已经做完了）。
backups_of() {  # $1 = db 或 media；输出用 NUL 分隔（备份目录的路径里可能有空格）
    local f
    for f in "$BACKUP_DIR/$1-"*.gz "$BACKUP_DIR/$1-"*.gz.gpg; do
        [[ -e "$f" ]] && printf '%s\0' "$f"
    done
}

# 按保留份数清理旧的 db 与 media 备份（各自独立保留 RETAIN 份）
prune() {
    local files=() doomed=() f i=0
    mapfile -t -d '' files < <(backups_of "$1")
    [[ ${#files[@]} -gt 0 ]] || return 0
    # 刚写出的那几份也要一并收紧权限：gzip/tar 按 umask 创建（常见 644 = 同机所有账号
    # 可读），目录里更早的历史备份同样不该因为「那时还没加这一步」而一直敞着。
    chmod 600 "${files[@]}" 2>/dev/null || true

    # 挑出该删的，**全程 NUL 分隔，不借 ls -1t 排序**：ls 的输出按行，名字里一旦有空格
    # （备份目录的路径本身就带空格时就会）或换行，后面的 rm 会把它拆成两半——而脚本开头
    # cd 到了 $APP_DIR，那些碎片于是当**相对路径**解析，会误删应用目录下的同名文件；同时
    # rm 报错让 xargs 以 123 退出，整轮在生产完备份之后中止（保留份数从此再也不生效）。
    # 按文件名倒序即可：产物名里就带时间戳（<前缀>-<日期>-<时分>），字典序即时间序。
    while IFS= read -r -d '' f; do
        (( i < RETAIN )) || doomed+=("$f")
        i=$((i + 1))
    done < <(printf '%s\0' "${files[@]}" | sort -zr)
    (( ${#doomed[@]} > 0 )) && rm -f -- "${doomed[@]}"
    return 0
}
prune db
prune media

echo "[$(date '+%F %T')] 备份完成: ${PRODUCED[*]}"

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