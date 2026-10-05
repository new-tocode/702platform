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

# env.sh 里是数据库口令、SECRET_KEY 与超管口令。它由 install.sh 从模板 cp 而来，
# 权限随 umask（实测生产上曾是 664，同机其它账号可读）。install.sh 每次运行都会收紧，
# 但**日常部署走的是本脚本**，所以这里也收一次。
#
# 放在 source 之前（先收紧再读内容），也放在切换用户之前（两种调用方式都覆盖到；
# chmod 只改模式位，不改属主，所以以 root 身份先做也不会把属主弄错）。
if [[ -f env.sh ]] && [[ "$(stat -c '%a' env.sh)" != "600" ]]; then
    chmod 600 env.sh
    echo "    已将 env.sh 权限收紧为 600（内含数据库口令与 SECRET_KEY）"
fi

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


echo "==> 0/6 上线前预检：证书与备份"
# 这两项都是「坏了不会让站点立刻出错、等发现时已经晚了」的那一类，而它们恰好都
# 不在部署流程的覆盖范围内：
#   * 证书到期 —— 所有人浏览器弹警告，而续期要走签发流程，不是几分钟能补的；
#   * 备份停摆 —— 真需要恢复时才发现手里那份数据是几天前的。
# 所以每次部署都把状态摊在眼前。**只警告、不中止**：这两件事都不是本次发布能修的，
# 卡住发布只会让人学会绕过这道检查——旁边那道 check --deploy 门禁会跟着失去威信。
#
# 这条预检是补一个真实的坑：生产上备份定时器曾连续 5 天以 226/NAMESPACE 失败，
# 而它没有任何告警，直到有人去翻 journal 才发现。定时器的失败不会自己冒出来，
# 必须有人问它。

# 证书还有多久到期。/etc/letsencrypt/live/ 是 700 root，部署用户通常读不到证书
# 文件，所以读不到时改问本机 443 上的服务要——两条路都拿不到就跳过，不猜。
CERT_END=""
if command -v openssl >/dev/null 2>&1 && [[ -n "${SSL_CERT_PATH:-}" ]]; then
    if [[ -r "${SSL_CERT_PATH:-/nonexistent}" ]]; then
        CERT_END="$(openssl x509 -in "$SSL_CERT_PATH" -noout -enddate 2>/dev/null | cut -d= -f2 || true)"
    else
        CERT_END="$(echo \
            | timeout 10 openssl s_client -connect 127.0.0.1:443 \
                -servername "${DEPLOY_DOMAIN:-127.0.0.1}" 2>/dev/null \
            | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2 || true)"
    fi
fi
if [[ -n "$CERT_END" ]]; then
    if [[ "$(date -d "$CERT_END" +%s 2>/dev/null || echo 0)" -gt "$(( $(date +%s) + 21 * 24 * 3600 ))" ]]; then
        echo "    ✅ 证书 21 天内不会到期（到期：$CERT_END）"
    else
        echo "    ⚠️  证书将在 21 天内到期（到期：$CERT_END）" >&2
        echo "       确认续期在跑：systemctl list-timers certbot-renew.timer --all" >&2
        echo "                     sudo certbot renew --dry-run" >&2
    fi
fi

# 备份：定时器上次运行的结果，以及最近一份产物有多老。
BACKUP_DIR="${DJANGO_BACKUP_DIR:-$APP_DIR/backups}"
BACKUP_RESULT="$(systemctl show club702-backup.service -p Result --value 2>/dev/null || true)"
if [[ "$BACKUP_RESULT" == "exit-code" || "$BACKUP_RESULT" == "signal" || "$BACKUP_RESULT" == "core-dump" ]]; then
    echo "    ⚠️  备份定时器上次运行失败（Result=$BACKUP_RESULT）" >&2
    echo "       journalctl -u club702-backup -n 20" >&2
fi
if [[ -d "$BACKUP_DIR" ]]; then
    NEWEST_TS="$(find "$BACKUP_DIR" -maxdepth 1 -name 'db-*.sql.gz' -printf '%T@\n' 2>/dev/null | sort -rn | head -1 || true)"
    if [[ -z "$NEWEST_TS" ]]; then
        echo "    ⚠️  $BACKUP_DIR 下没有任何数据库备份产物" >&2
    else
        AGE_HOURS=$(( ( $(date +%s) - ${NEWEST_TS%.*} ) / 3600 ))
        if [[ "$AGE_HOURS" -gt 30 ]]; then
            echo "    ⚠️  最近一份数据库备份在 ${AGE_HOURS} 小时前（定时器预期每 24 小时一份）" >&2
            echo "       systemctl status club702-backup --no-pager" >&2
        else
            echo "    ✅ 最近一份数据库备份在 ${AGE_HOURS} 小时前"
        fi
    fi
fi

# ---- 服务器基线提醒（只报告，不改系统）----
# 这三项都属于「以为有、其实没有」：防火墙没启用、没有自动安全更新、fail2ban 的
# 封禁动作指向一个没在运行的防火墙。它们平时不报错，只在真出事那天被发现，
# 所以每次部署都报一遍——**修好之后这几行会自己消失**，不会变成长期噪音。
#
# 只提醒不动手，是刻意的：装防火墙、开自动更新、换 banaction 改的是整台机器的
# 状态（同机上还有别人的站点），那该由人决定，不该由一次应用发布顺手做掉。
BASELINE=()
if ! systemctl is-active --quiet firewalld 2>/dev/null \
    && ! systemctl is-active --quiet nftables 2>/dev/null \
    && ! systemctl is-active --quiet ufw 2>/dev/null; then
    BASELINE+=("主机没有启用的防火墙（firewalld / nftables / ufw 均未运行）——网络边界只剩云安全组")
fi
if ! systemctl is-active --quiet dnf-automatic.timer 2>/dev/null \
    && ! systemctl is-active --quiet dnf-automatic-install.timer 2>/dev/null \
    && ! systemctl is-active --quiet yum-cron 2>/dev/null \
    && ! systemctl is-active --quiet unattended-upgrades 2>/dev/null; then
    BASELINE+=("没有自动安全更新（dnf-automatic / yum-cron / unattended-upgrades 均未运行）——系统包只能靠人工升级")
fi
# fail2ban 的 banaction 要取**真正生效**的那个值，不能「任意一个文件里出现过
# firewallcmd 就报警」：配置是层层覆盖的（jail.conf < jail.d/*.conf 按字母序 <
# jail.local），后面的盖前面的——而「换个封禁后端」的标准做法正是加一个排在后面的
# 覆盖文件。只看有没有出现过，会把做对了的人一直报成错的。
#
# 只认 [DEFAULT] 段里的那条：jail.conf 在别的 jail 段里还有 `banaction =
# %(banaction_allports)s` 这种引用，抓到它就会得出一个毫无意义的结论。
effective_banaction() {
    local file value=""
    for file in /etc/fail2ban/jail.conf /etc/fail2ban/jail.d/*.conf /etc/fail2ban/jail.local; do
        [[ -r "$file" ]] || continue
        local found
        found="$(awk '
            /^\[/ { in_default = ($0 ~ /^\[DEFAULT\]/) ; next }
            in_default && /^[[:space:]]*banaction[[:space:]]*=/ {
                line = $0; sub(/^[^=]*=[[:space:]]*/, "", line); value = line
            }
            END { if (value != "") print value }
        ' "$file" 2>/dev/null || true)"
        [[ -n "$found" ]] && value="$found"
    done
    printf '%s' "$value"
}

# 「装了、也设了开机自启，却没在跑」——封禁这件事此刻是空着的。这一条原先看不见：
# 老的条件要求 fail2ban 在跑才检查它的配置，于是停掉它反而什么都不报。
if [[ "$(systemctl is-enabled fail2ban 2>/dev/null || true)" == "enabled" ]] \
    && ! systemctl is-active --quiet fail2ban 2>/dev/null; then
    BASELINE+=("fail2ban 装了、也设了开机自启，但现在没在跑——封禁这件事此刻是空着的")
elif systemctl is-active --quiet fail2ban 2>/dev/null \
    && ! systemctl is-active --quiet firewalld 2>/dev/null \
    && [[ "$(effective_banaction)" == firewallcmd* ]]; then
    BASELINE+=("fail2ban 在跑，但 banaction 是 firewallcmd-*（firewalld 没运行）——封禁动作落不了地")
fi
if [[ "${#BASELINE[@]}" -gt 0 ]]; then
    echo "    ⚠️  服务器基线（只提醒，脚本不改系统）：" >&2
    for item in "${BASELINE[@]}"; do
        echo "        - $item" >&2
    done
fi

# ---- 配置漂移：/etc 下的东西还是不是仓库模板渲染后的样子 ----
# 这一类我们踩过两次：备份的 systemd 单元与 nginx 配置在仓库里都改好了，线上却是
# 几个月前那版——那两样都归 install.sh 装，而 install.sh 是一次性脚本；日常部署
# 走的是本脚本，它以降权用户运行（见上面那段 exec sudo -u），碰不了 /etc。
# 于是「修好了」只发生在仓库里，线上一点没变，而且没有任何东西会说出来。
#
# 本脚本改不了 /etc，但**读得到**，所以把不一致摊出来。修法是重跑一次 install.sh
# ——它是幂等的，也不会覆盖 env.sh（只校验）。
DRIFT=()

# PostgreSQL 的单元名随发行版与版本而变，与 install.sh 同一套探测逻辑。
PG_SERVICE_DETECTED="$(systemctl list-unit-files --type=service --no-pager 2>/dev/null \
    | awk '/^postgresql\.service[[:space:]]/ {deb=$1} /^postgresql-[0-9]+\.service[[:space:]]/ {if (!ver) ver=$1} END {print (deb ? deb : ver)}' || true)"
PG_SERVICE_DETECTED="${PG_SERVICE_DETECTED:-postgresql.service}"

RENDER=(
    -e "s|@@APP_DIR@@|$APP_DIR|g"
    -e "s|@@APP_USER@@|${DEPLOY_SYSTEM_USER:-}|g"
    -e "s|@@APP_HOST@@|$APP_HOST|g"
    -e "s|@@APP_PORT@@|$APP_PORT|g"
    -e "s|@@VENV@@|$APP_DIR/.venv|g"
    -e "s|@@BACKUP_DIR@@|${DJANGO_BACKUP_DIR:-/var/backups/club702}|g"
    -e "s|@@BACKUP_SCHEDULE@@|${DJANGO_BACKUP_SCHEDULE:-daily}|g"
    -e "s|@@PG_SERVICE@@|$PG_SERVICE_DETECTED|g"
)

# 去掉注释、空行与行首行尾空白再比：只改了一句注释就长期报警的话，这道检查很快
# 会被无视——而它要拦的恰恰是「模板改了、线上没跟上」这种真差异。
_normalize_unit() {   # 从标准输入读
    grep -vE '^[[:space:]]*(#|$)' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

unit_drift() {  # unit_drift <模板> <线上文件> <说明>
    local template="$1" deployed="$2" label="$3"
    [[ -r "$deployed" ]] || return 0     # 读不到就不猜（可能不是本机装的）
    if ! diff -q \
        <(sed "${RENDER[@]}" "$template" | _normalize_unit) \
        <(_normalize_unit < "$deployed") >/dev/null 2>&1; then
        DRIFT+=("$label")
    fi
}
unit_drift "$APP_DIR/deploy/club702.service" /etc/systemd/system/club702.service "应用单元 club702.service"
unit_drift "$APP_DIR/deploy/club702-backup.service" /etc/systemd/system/club702-backup.service "备份单元 club702-backup.service"
unit_drift "$APP_DIR/deploy/club702-backup.timer" /etc/systemd/system/club702-backup.timer "备份定时器 club702-backup.timer"

# nginx 不做整份 diff：install.sh 渲染之后还要按「有没有证书」删掉 HTTPS 段的标记
# 行，整份比对必然长期误报。改成直接断言那几条加固在不在线上文件里——这样报出来
# 的每一条都是真的缺东西。
NGINX_SITE_CONF=""
for candidate in /etc/nginx/conf.d/club702.conf /etc/nginx/sites-enabled/club702; do
    if [[ -r "$candidate" ]]; then NGINX_SITE_CONF="$candidate"; break; fi
done
if [[ -n "$NGINX_SITE_CONF" ]]; then
    grep -qF 'limit_req zone=club702_login' "$NGINX_SITE_CONF" \
        || DRIFT+=("nginx 站点配置里没有登录限流（limit_req）")
    grep -qF 'location ~ /\.(?!well-known)' "$NGINX_SITE_CONF" \
        || DRIFT+=("nginx 站点配置里没有对 /. 开头路径的拒绝规则")
    grep -qF 'X-Forwarded-For $remote_addr' "$NGINX_SITE_CONF" \
        || DRIFT+=("nginx 仍用 \$proxy_add_x_forwarded_for 转发来源 IP——应用侧 TRUST_FORWARDED_FOR 会因此不成立")
    # ACME 挑战的落点。少了它，certbot 的 http-01 验证会落到 location / 被反代给
    # Django 而 404，报错写成「验证文件取不到」，看着像网络问题。
    grep -qF '/.well-known/acme-challenge/' "$NGINX_SITE_CONF" \
        || DRIFT+=("nginx 站点配置里没有 ACME 挑战的 location（证书签发与续期会失败）")
    # 443 必须是 default_server。访问 https://<IP> 时浏览器不发 SNI，nginx 只能回落到
    # 该端口的默认 server——没声明时是同机配置顺序里的第一个，往往不是本平台，于是
    # IP 证书签得再对也用不上：客户端拿到别人的证书，浏览器照样报错。
    if grep -qF 'listen 443' "$NGINX_SITE_CONF"; then
        grep -qF 'listen 443 ssl default_server' "$NGINX_SITE_CONF" \
            || DRIFT+=("nginx 的 443 没有声明 default_server——按 IP 访问会拿到别的站点的证书")
    fi
    if [[ -r /etc/nginx/nginx.conf ]]; then
        grep -qF 'zone=club702_login' /etc/nginx/nginx.conf \
            || DRIFT+=("nginx.conf 里没有 limit_req_zone club702_login 的定义（站点配置引用了它）")
    fi
fi

if [[ "${#DRIFT[@]}" -gt 0 ]]; then
    echo "    ⚠️  /etc 下的配置与仓库模板不一致（本脚本改不了，要重跑 install.sh）：" >&2
    for item in "${DRIFT[@]}"; do
        echo "        - $item" >&2
    done
    echo "        sudo $APP_DIR/deploy/install.sh    # 幂等；不会覆盖 env.sh" >&2
fi

echo "==> 1/6 备份数据库和媒体（分别保留 ${DJANGO_BACKUP_RETAIN:-14} 份）"
# 直接复用 backup.sh，不再在这里抄一遍 pg_dump 与 tar：两份实现迟早会漂移，而
# 「发布前先备份」是回滚的前提，它出错没人会发现——直到真需要回滚的那一天。
"$APP_DIR/deploy/backup.sh"

echo "==> 2/6 切换版本 $TAG"
git fetch --tags origin
git checkout "$TAG"

echo "==> 3/6 安装/更新依赖"
# --require-hashes：锁文件里每个包都带哈希，安装时校验——依赖被篡改或供应链
# 投毒会在这里失败，而不是安静地装上一个被换过的包。
.venv/bin/python -m pip install --quiet --require-hashes \
    -r requirements.txt -r requirements-prod.txt

echo "==> 4/6 部署配置门禁"
# check --deploy 会在上线之前把「DEBUG 还开着」「Cookie 没带 Secure」「SECRET_KEY
# 还是源码默认值」这类退化拦下来。这类问题不会让站点起不来，只会让它安静地不安全，
# 事后再发现往往已经跑了一段时间。所以放在重启服务之前：宁可这次发布失败。
.venv/bin/python manage.py check --deploy --fail-level WARNING

echo "==> 5/6 数据库迁移 + 静态文件 + 界面翻译"
# 受保护上传件的目录（项目书、批注版、头像、图册）。它是后加的，老部署上没有；
# 不先建出来，迁移里的文件搬运无处落脚、应用写入也会失败。install.sh 也会建，
# 但日常部署走的是本脚本，这里不能省。
mkdir -p protected_media

# 历年获奖的判重要用 pg_trgm（content.0004_pg_trgm 会 CREATE EXTENSION）。它在多数
# 发行版里是**单独的包**——PGDG 的 RPM 装在 postgresql<ver>-contrib 里，只装 server
# 是没有的。缺了的话 migrate 会抛一大段 traceback（"extension pg_trgm is not
# available"），看不出该怎么办；先探一下目录（pg_available_extensions 只读文件系统
# 目录，不碰业务表），缺了就给可照做的安装命令。
#
# 退出码：0 = 可用；1 = 连上了库但没有这个扩展；其他 = 连库本身失败（不在这里多说，
# 后头的 migrate 会给出真正的错误）。
pg_trgm_status=0
.venv/bin/python manage.py shell -c '
from django.db import connection
try:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_available_extensions WHERE name = %s", ["pg_trgm"])
        available = cursor.fetchone() is not None
except Exception:
    raise SystemExit(2)
raise SystemExit(0 if available else 1)
' >/dev/null 2>&1 || pg_trgm_status=$?
if [ "$pg_trgm_status" -eq 1 ]; then
    echo "    数据库缺 pg_trgm 扩展（PostgreSQL 未装 contrib 包）：" >&2
    echo "      RHEL 系（PGDG）: sudo dnf install -y postgresql<主版本>-contrib" >&2
    echo "      Debian / Ubuntu: sudo apt install postgresql-contrib" >&2
    echo "    装好后重跑本脚本即可，不需要重启 PostgreSQL。" >&2
    exit 1
fi

.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py collectstatic --noinput
# 界面英文的 .mo 是构建产物（不进版本库）：按这个 tag 里的 .po 现编，线上就永远
# 与 .po 一致。服务器缺 gettext 会在这里直接失败——比英文页面静默退回中文好。
.venv/bin/python manage.py compilemessages -l en

echo "==> 6/6 重启服务 + 健康检查"
systemctl restart "$SERVICE_NAME"

# 健康检查优先打 Nginx，打不通再退回直连 gunicorn。
#
# 早先只打 http://$APP_HOST:$APP_PORT，那其实只验证了三件事里的一件：Django 自己
# 活没活。对外能用要三件同时对——Django 活着、gunicorn 在监听、Nginx 在前面把请求
# 正确转过去。少了最后一件，成员看到的是 502，而这道门禁会绿着报「上线成功」。
# 反过来，Nginx 若不在本机（或没监听 127.0.0.1:80），只打 Nginx 又会把一次正常的
# 发布判成失败。所以是「先试 Nginx，不行退回直连」：两条路都拿不到才算失败，
# 而且成功时会打印这次究竟验到了哪一层。
#
# 打 Nginx 必须自带 Host 头——Nginx 靠 server_name 选虚拟主机，不带就会落到
# default_server 上去。这里复用 DEPLOY_DOMAIN / DEPLOY_PUBLIC_IP：install.sh 已经
# 用这两个值生成 Nginx 的 server_name，所以不另立配置项，两边不会漂移。
PUBLIC_HOST="${DEPLOY_DOMAIN:-${DEPLOY_PUBLIC_IP:-$APP_HOST}}"
PUBLIC_PORT="${DEPLOY_PUBLIC_PORT:-80}"
PUBLIC_URL="http://127.0.0.1:${PUBLIC_PORT}/"

# 每条路试 3 次、间隔 1 秒：重启后 gunicorn 其实已经 READY（club702.service 是
# Type=notify），但 Nginx 到 upstream 的首个连接仍可能撞上 worker 换血的瞬间拿到
# 502。失败一次就判死，会让一次正常发布误报为失败。
# 注意 -f 只把 4xx/5xx 当失败，3xx 算通过：开了 DJANGO_SECURE_SSL_REDIRECT 时首页
# 返回 301，那同样说明这条链路是活的。
try_url() {  # try_url <url> [curl 额外参数...]
    local url="$1"; shift
    local i
    for i in 1 2 3; do
        if curl -fs -o /dev/null -m 10 "$@" "$url" 2>/dev/null; then
            return 0
        fi
        sleep 1
    done
    return 1
}

if try_url "$PUBLIC_URL" -H "Host: $PUBLIC_HOST"; then
    HEALTH="经 Nginx（Host: $PUBLIC_HOST → 127.0.0.1:$PUBLIC_PORT）"
elif try_url "$SITE_URL"; then
    HEALTH="直连 gunicorn（$SITE_URL，未经 Nginx）"
else
    echo "❌ 健康检查失败：Nginx 与 gunicorn 两条路都不通" >&2
    echo "   诊断:" >&2
    echo "     curl -i -H 'Host: $PUBLIC_HOST' $PUBLIC_URL   # 期望 200" >&2
    echo "     curl -i $SITE_URL                             # 期望 200（直连要求 DJANGO_ALLOWED_HOSTS 含 127.0.0.1）" >&2
    echo "     journalctl -u $SERVICE_NAME -n 50 ; journalctl -u nginx -n 50" >&2
    # 回滚**不要**重跑本脚本：它第一步是备份、第五步是正向 migrate，方向与回滚相反。
    echo "   回滚（手工三步，说明见 docs/deploy.md 的「更新与回滚」）:" >&2
    echo "     set -a; source env.sh; set +a" >&2
    echo "     git checkout <上一个tag>" >&2
    echo "     .venv/bin/python manage.py migrate --noinput   # 仅当这一版带了迁移" >&2
    echo "     systemctl restart $SERVICE_NAME" >&2
    echo "   数据库也要退回去时，用发布前那份备份手工恢复；重跑 deploy.sh 做不到这件事。" >&2
    exit 1
fi
echo "✅ 上线成功: $TAG"
echo "   健康检查: $HEALTH"
