#!/usr/bin/env bash
# 一键提交并部署 dailyReport。默认目标：mesdev@mesdevserver:~/deploy/daily-report。
set -Eeuo pipefail

SSH_HOST="mesdevserver"
CHECK_ONLY=0
if [[ "${1:-}" != "" && "${1:-}" != --* ]]; then SSH_HOST="$1"; fi
SKIP_TESTS="${SKIP_TESTS:-0}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB="daily-report-web"
APP="daily-report"
GROUP_ID="cid6vVsD8T971qSRMK+06RykA=="

fail() {
  local rc="$?"
  echo "[失败] $1（退出码 ${rc}）"
  echo "[排查] ssh mesdev@${SSH_HOST} 'docker logs --tail 100 ${WEB}'"
  echo "[排查] ssh mesdev@${SSH_HOST} 'docker ps -a --filter name=${APP}'"
  echo "[排查] ssh mesdev@${SSH_HOST} 'docker exec ${WEB} python manage.py send_payment_report week --group-id ${GROUP_ID}'"
  exit "$rc"
}
trap 'fail "第 ${LINENO} 行执行失败：${BASH_COMMAND}"' ERR

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" || "${2:-}" == "--help" || "${2:-}" == "-h" ]]; then
  echo "用法：bash scripts/deploy_one_click.sh [SSH主机] [--check]"
  echo "默认：测试、提交、推送、调用 deploy_remote.sh、输出排查命令"
  echo "跳过本地测试：SKIP_TESTS=1 bash scripts/deploy_one_click.sh"
  exit 0
fi

if [[ "${1:-}" == "--check" || "${2:-}" == "--check" ]]; then
  CHECK_ONLY=1
fi

cd "$ROOT_DIR"
command -v git >/dev/null || fail "本机找不到 git"
command -v ssh >/dev/null || fail "本机找不到 ssh"
[[ -f scripts/deploy_remote.sh ]] || fail "找不到 scripts/deploy_remote.sh"
ssh -o BatchMode=yes -o ConnectTimeout=10 "mesdev@${SSH_HOST}" true || fail "SSH 连接失败"

if [[ "$CHECK_ONLY" -eq 1 ]]; then
  ssh "mesdev@${SSH_HOST}" "docker ps --filter name=${APP} --format '{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}'"
  exit 0
fi

if [[ "$SKIP_TESTS" != 1 ]]; then
  echo "==> 运行付款报表回归测试"
  if [[ -x .tmp/payment-test-deps/Scripts/python.exe ]]; then
    PYTHONPATH="$ROOT_DIR/.tmp/payment-test-deps" .tmp/payment-test-deps/Scripts/python.exe manage.py test integrations.tests.test_payment_delivery integrations.tests.test_payment_report integrations.tests.test_dingtalk_sync --verbosity 1
  elif command -v python >/dev/null; then
    python manage.py test integrations.tests.test_payment_delivery integrations.tests.test_payment_report integrations.tests.test_dingtalk_sync --verbosity 1
  else
    fail "找不到 Python；如已完成外部验证，可设置 SKIP_TESTS=1"
  fi
else
  echo "==> SKIP_TESTS=1，跳过本地测试"
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "==> 提交当前工作区改动"
  git add -A
  git commit -m "fix: 更新 dailyReport $(date +%Y-%m-%d)"
  echo "==> 推送 origin/main"
  git push origin HEAD:main
else
  echo "==> 工作区没有新改动，跳过提交"
fi

echo "==> 调用远程部署脚本：mesdev@${SSH_HOST}:~/deploy/daily-report"
bash scripts/deploy_remote.sh "$SSH_HOST"
echo
echo "[完成] 已完成提交、推送和部署"
echo "[验证] ssh mesdev@${SSH_HOST} 'docker exec ${WEB} python manage.py send_payment_report week --group-id ${GROUP_ID}'"
