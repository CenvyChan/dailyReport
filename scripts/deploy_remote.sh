#!/usr/bin/env bash
# 通过 SSH 把项目部署到远端 Docker 主机（重复执行即为重新部署）。
#
# 用法：  bash scripts/deploy_remote.sh [ssh-host] [宿主机端口]
# 默认：  bash scripts/deploy_remote.sh mesdevserver 8001
#
# 目标主机只需要有 docker，不需要 compose 插件，也不会安装任何系统级依赖。
# 源码用 tar over ssh 传输，本机不需要 rsync（Git Bash 下没有 rsync）。
# data/ 不传输，服务器上的数据库不会被本地库覆盖。
set -euo pipefail

SSH_HOST="${1:-mesdevserver}"
HOST_PORT="${2:-8001}"
APP_NAME="daily-report"
IMAGE="${APP_NAME}:latest"
WEB="${APP_NAME}-web"
MAILER="${APP_NAME}-mailer"

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> 目标 ${SSH_HOST}，对外端口 ${HOST_PORT}"
ssh "$SSH_HOST" 'mkdir -p ~/deploy/'"${APP_NAME}"'/data ~/deploy/'"${APP_NAME}"'/backups'

echo "==> 传输源码"
tar -czf - --exclude='__pycache__' --exclude='*.pyc' \
  Dockerfile .dockerignore requirements.txt manage.py \
  config core sales purchase reports notifications scripts static templates docs \
  | ssh "$SSH_HOST" 'tar -xzf - -C ~/deploy/'"${APP_NAME}"

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
REMOTE

echo "==> 构建镜像"
ssh "$SSH_HOST" 'cd ~/deploy/'"${APP_NAME}"' && docker build -t '"${IMAGE}"' .'

echo "==> 重建容器"
ssh "$SSH_HOST" "APP_NAME='${APP_NAME}' IMAGE='${IMAGE}' WEB='${WEB}' MAILER='${MAILER}' HOST_PORT='${HOST_PORT}' bash -s" <<'REMOTE'
set -euo pipefail
cd ~/deploy/"$APP_NAME"

# 只删本应用的容器，不影响主机上其它容器。
docker rm -f "$WEB" "$MAILER" >/dev/null 2>&1 || true

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
