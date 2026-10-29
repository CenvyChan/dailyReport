#!/usr/bin/env bash
# 一键：测试 → 提交 → 推送 → 服务器构建并重建容器。
#
# 用法：bash scripts/deploy_one_click.sh "提交说明" [SSH主机]
#       bash scripts/deploy_one_click.sh --check [SSH主机]   只看线上容器状态
#       SKIP_TESTS=1 bash scripts/deploy_one_click.sh "提交说明"
#
# 提交规则：只自动暂存「已跟踪文件」的改动（git add -u）。
# 出现未跟踪的新文件时直接停止，要求先 git add 或写进 .gitignore，
# 避免调试脚本、交接包之类被顺手提交推送。
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  sed -n '2,10p' "$0"; exit 0
fi

if [[ "${1:-}" == "--check" ]]; then
  ssh "${2:-mesdevserver}" "docker ps --filter name=daily-report --format '{{.Names}}|{{.Image}}|{{.Status}}'"
  exit 0
fi

MSG="${1:-}"
SSH_HOST="${2:-mesdevserver}"
trap 'echo "[失败] 第 ${LINENO} 行：${BASH_COMMAND}"; echo "[排查] ssh ${SSH_HOST} docker logs --tail 100 daily-report-web"' ERR

ssh -o BatchMode=yes -o ConnectTimeout=10 "$SSH_HOST" true

untracked="$(git ls-files --others --exclude-standard)"
if [[ -n "$untracked" ]]; then
  echo "!! 存在未跟踪文件，请先 git add（要上线的）或加入 .gitignore（不要的）："
  echo "$untracked" | sed 's/^/   /'
  exit 1
fi

if [[ "${SKIP_TESTS:-0}" != 1 ]]; then
  echo "==> 运行回归测试"
  python manage.py test integrations notifications core --verbosity 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  [[ -n "$MSG" ]] || { echo "!! 有改动待提交，请提供提交说明作为第一个参数"; exit 1; }
  git add -u
  git commit -m "$MSG"
else
  echo "==> 工作区干净，直接部署 HEAD"
fi

branch="$(git rev-parse --abbrev-ref HEAD)"
echo "==> 推送 origin/${branch}"
git push origin "HEAD:${branch}"

bash scripts/deploy_remote.sh "$SSH_HOST"
echo "[完成] 已部署 $(git rev-parse --short HEAD)；回滚标签见：ssh ${SSH_HOST} docker images daily-report"
