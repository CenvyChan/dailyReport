#!/usr/bin/env bash
# 通过 SSH 把「已提交的代码」部署到远端 Docker 主机，在服务器上构建镜像。
#
# 用法：  bash scripts/deploy_remote.sh [ssh-host] [宿主机端口]
# 回滚：  ROLLBACK_TAG=20261029-1830-1a2b3c4 bash scripts/deploy_remote.sh
#         跳过传输和构建，直接用服务器上已有的镜像标签重建容器。
#         查看可回滚标签：ssh mesdevserver 'docker images daily-report'
#
# 源码取自 git HEAD（git archive），未提交的改动不会上线，线上版本始终对应某个提交。
# 每个版本解压到 ~/deploy/daily-report/.releases/<标签>/ 单独构建，删掉的旧文件不会残留。
# data/、backups/、.env 留在 ~/deploy/daily-report/，不传输、不覆盖。
set -euo pipefail

SSH_HOST="${1:-mesdevserver}"
HOST_PORT="${2:-8001}"
APP_NAME="daily-report"
WEB="${APP_NAME}-web"
MAILER="${APP_NAME}-mailer"
BACKUP="${APP_NAME}-backup"
SYNC="${APP_NAME}-sync"
SCHEDULER="${APP_NAME}-scheduler"

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -n "${ROLLBACK_TAG:-}" ]; then
  TAG="$ROLLBACK_TAG"
else
  TAG="$(date +%Y%m%d-%H%M)-$(git rev-parse --short HEAD)"
fi
IMAGE="${APP_NAME}:${TAG}"
# ssh 登录后位于 $HOME，用相对路径避免 ~ 在引号里不展开。
RELEASE="deploy/${APP_NAME}/.releases/${TAG}"

echo "==> 目标 ${SSH_HOST}，对外端口 ${HOST_PORT}，镜像 ${IMAGE}"
ssh "$SSH_HOST" "mkdir -p deploy/${APP_NAME}/data deploy/${APP_NAME}/backups"

if [ -z "${ROLLBACK_TAG:-}" ]; then
  if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    echo "!! 注意：工作区有未提交改动，这些改动不会被部署（只部署 HEAD $(git rev-parse --short HEAD)）"
  fi
  echo "==> 传输源码：git archive HEAD → ~/${RELEASE}"
  git archive --format=tar.gz HEAD | ssh "$SSH_HOST" "mkdir -p ${RELEASE} && tar -xzf - -C ${RELEASE}"
fi

echo "==> 生成 .env（已存在则保留，不覆盖已配好的邮箱口令）"
ssh "$SSH_HOST" "APP_NAME='${APP_NAME}' HOST_PORT='${HOST_PORT}' bash -s" <<'REMOTE'
set -euo pipefail
cd ~/deploy/"$APP_NAME"
if [ -f .env ]; then
  echo "沿用已有 .env"
else
  IP=$(hostname -I | awk '{print $1}')
  {
    echo "DJANGO_SECRET_KEY=$(python3 -c 'import secrets;print(secrets.token_urlsafe(64))')"
    echo "DJANGO_DEBUG=False"
    echo "DJANGO_ALLOWED_HOSTS=${IP},localhost,127.0.0.1"
    echo "DJANGO_CSRF_TRUSTED_ORIGINS=http://${IP}:${HOST_PORT}"
    echo "BACKUP_DIRECTORY=/app/backups"
    # 日志放在 data 卷下：单独挂 logs 会因宿主机属主与容器 uid 10001 不同而不可写
    echo "LOG_DIRECTORY=/app/data/logs"
    echo "EMAIL_HOST=smtp.qiye.aliyun.com"
    echo "EMAIL_PORT=465"
    echo "EMAIL_USE_SSL=True"
    echo "EMAIL_USE_TLS=False"
    echo "EMAIL_HOST_USER="
    echo "EMAIL_HOST_PASSWORD="
    echo "DEFAULT_FROM_EMAIL="
  } > .env
  chmod 600 .env
  echo "已生成新的 .env（邮件相关字段待填）"
fi

# 集成密钥字段静态加密密钥：缺失则补一枚，已存在则原样保留（覆盖会让已存密文失效）。
# Fernet key = urlsafe-base64(32 随机字节)，用标准库生成，宿主机无需装 cryptography。
if ! grep -q '^FIELD_ENCRYPTION_KEY=' .env; then
  python3 -c "import os,base64;print('FIELD_ENCRYPTION_KEY='+base64.urlsafe_b64encode(os.urandom(32)).decode())" >> .env
  echo "已补充 FIELD_ENCRYPTION_KEY（首次生成，请勿再变更，否则已存密文无法解密）"
fi
REMOTE

if [ -z "${ROLLBACK_TAG:-}" ]; then
  echo "==> 在服务器上构建镜像 ${IMAGE}"
  ssh "$SSH_HOST" "cd ${RELEASE} && docker build -t ${IMAGE} -t ${APP_NAME}:latest ."
else
  echo "==> 回滚模式：跳过构建，使用已有镜像 ${IMAGE}"
  ssh "$SSH_HOST" "docker image inspect ${IMAGE} >/dev/null" \
    || { echo "!! 服务器上没有镜像 ${IMAGE}"; exit 1; }
fi

echo "==> 重建容器"
ssh "$SSH_HOST" "APP_NAME='${APP_NAME}' IMAGE='${IMAGE}' WEB='${WEB}' MAILER='${MAILER}' BACKUP='${BACKUP}' SYNC='${SYNC}' SCHEDULER='${SCHEDULER}' HOST_PORT='${HOST_PORT}' bash -s" <<'REMOTE'
set -euo pipefail
cd ~/deploy/"$APP_NAME"

# 只删本应用的容器，不影响主机上其它容器。
docker rm -f "$WEB" "$MAILER" "$BACKUP" "$SYNC" "$SCHEDULER" >/dev/null 2>&1 || true

# 容器内以 uid 10001 运行，挂载目录必须可写，否则 SQLite 报 readonly database。
# 上一次部署后这些文件已归 10001，普通用户再 chmod 会 Permission denied，
# 所以两种方式都容错；真的没权限会在下面的健康检查里暴露出来。
sudo -n chown -R 10001:10001 data backups 2>/dev/null \
  || chmod -R u+rwX,g+rwX data backups 2>/dev/null \
  || echo "跳过权限调整（目录已归容器用户）"

docker run -d --name "$WEB" --restart unless-stopped \
  --env-file .env -p "${HOST_PORT}:8000" \
  -v "$PWD/data:/app/data" -v "$PWD/backups:/app/backups" \
  "$IMAGE" >/dev/null

# 复用同一镜像跑发信循环，替代计划任务；命令内部保证同一天不重复发送。
docker run -d --name "$MAILER" --restart unless-stopped \
  --env-file .env -v "$PWD/data:/app/data" \
  "$IMAGE" \
  sh -c 'while true; do sleep 600; python manage.py send_daily_report || true; done' >/dev/null

# 备份 sidecar。此前只加在 docker-compose.yml 里，而这台机器没有 compose
# 插件、走的是 plain docker run，等于自动备份根本没生效——上线后大概率没人
# 手工配 cron，data 卷一旦损坏就全丢。
# 先等 60 秒让 web 跑完 migrate，然后立刻备一次，之后每 24 小时一次，保留 30 份。
docker run -d --name "$BACKUP" --restart unless-stopped \
  --env-file .env \
  -v "$PWD/data:/app/data" -v "$PWD/backups:/app/backups" \
  "$IMAGE" \
  sh -c 'sleep 60; while true; do python scripts/backup_sqlite.py --keep 30 >> /app/data/logs/backup.log 2>&1 || true; sleep 86400; done' >/dev/null

# 集成同步 sidecar：每天 20 点后拉金蝶出入库 + 钉钉审批。命令对当天已同步做
# 幂等判断，故每 30 分钟检查一次、只在 20 点后真正执行一次。容器时区 Asia/Shanghai。
docker run -d --name "$SYNC" --restart unless-stopped \
  --env-file .env \
  -v "$PWD/data:/app/data" \
  "$IMAGE" \
  sh -c 'while true; do if [ "$(date +%H)" -ge 20 ]; then python manage.py sync_kingdee >> /app/data/logs/sync.log 2>&1 || true; python manage.py sync_dingtalk >> /app/data/logs/sync.log 2>&1 || true; fi; sleep 1800; done' >/dev/null

# 日报调度 sidecar：每 10 分钟一轮，先补当月近期金蝶数据（命令内部按小时幂等），
# 再生成前一自然日快照并推送到到点的渠道（钉钉群 / 邮件收件组），
# 最后按群配置推送到期的付款周报/月报（命令内部按回执防重复）。
# 这个容器此前只存在于 docker-compose.yml 和手工 docker run，而这台机器走的是
# plain docker run：部署脚本不管它 → 重新部署后它仍挂在旧镜像层上（代码更新不
# 生效），被 docker rm 掉也不会重建，定时投递会静默消失。故纳入脚本统一管理。
# 先 sleep 90 秒等 web 跑完 migrate。日志与其它 sidecar 一致写到 data 卷下。
docker run -d --name "$SCHEDULER" --restart unless-stopped \
  --env-file .env \
  -v "$PWD/data:/app/data" \
  "$IMAGE" \
  sh -c 'sleep 90; while true; do python manage.py sync_kingdee_recent --hour $(date +%H) >> /app/data/logs/scheduler.log 2>&1 || true; python manage.py generate_and_send_report >> /app/data/logs/scheduler.log 2>&1 || true; python manage.py send_scheduled_payment_reports >> /app/data/logs/scheduler.log 2>&1 || true; sleep 600; done' >/dev/null

ready=""
for _ in $(seq 1 20); do
  if [ "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${HOST_PORT}/accounts/login/")" = "200" ]; then
    ready=yes
    break
  fi
  sleep 3
done

docker ps --filter "name=$APP_NAME" --format '{{.Names}}	{{.Status}}	{{.Ports}}'
if [ -z "$ready" ]; then
  echo "!! 服务没能在 60 秒内就绪，最近日志："
  docker logs --tail 30 "$WEB"
  exit 1
fi
echo "==> http://$(hostname -I | awk '{print $1}'):${HOST_PORT}/"
REMOTE

echo "==> 完成。首次部署需创建管理员："
echo "    ssh ${SSH_HOST} \"docker exec -it ${WEB} python manage.py createsuperuser\""
