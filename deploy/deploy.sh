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

.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py collectstatic --noinput
# 界面英文的 .mo 是构建产物（不进版本库）：按这个 tag 里的 .po 现编，线上就永远
# 与 .po 一致。服务器缺 gettext 会在这里直接失败——比英文页面静默退回中文好。
.venv/bin/python manage.py compilemessages -l en

echo "==> 6/6 重启服务 + 健康检查"
systemctl restart "$SERVICE_NAME"
sleep 2
if curl -fsS "$SITE_URL" > /dev/null; then
    echo "✅ 上线成功: $TAG"
else
    echo "❌ 健康检查失败，请立即检查: journalctl -u $SERVICE_NAME -n 50" >&2
    echo "   回滚: git checkout <上一个tag> && ./deploy/deploy.sh <上一个tag>" >&2
    exit 1
fi