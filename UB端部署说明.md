# dailyReport 生产部署说明

## 唯一生产位置

- SSH：`ssh mesdevserver`（`mesdev@172.16.77.80`）。
- 项目目录：`~/deploy/daily-report`，绝对路径 `/home/mesdev/deploy/daily-report`。
- Web 入口：`http://172.16.77.80:8001/`；容器内端口 8000。
- 容器：`daily-report-web`、`daily-report-mailer`、`daily-report-backup`、`daily-report-sync`、`daily-report-scheduler`。
- 持久化数据：项目目录下 `data/`、`backups/`；线上 `.env` 和加密密钥必须保留，不得用本地配置覆盖。

> 2026-10-28 已确认：不要使用 `/data/dailyReport`、`~/dailyReport`、旧用户 `cenvy` 或 `/home/mesdev/fns-plm`。生产目录是文件发布目录，不是 Git 仓库；服务器当前未安装 Compose，不可在此执行 `git pull` 或依赖 `docker compose` / `docker-compose`。

## 发布前核验

在本地使用 Git Bash 的 SSH（`C:/Program Files/Git/usr/bin/ssh.exe`），避免旧 Windows OpenSSH 在管道环境挂起。先执行：

```bash
ssh mesdevserver 'set -eu; cd "$HOME/deploy/daily-report"; pwd -P; test -f manage.py; docker ps --filter name=daily-report --format "{{.Names}} | {{.Image}} | {{.Status}} | {{.Ports}}"'
```

必须与上述目录、五个容器和 8001 端口匹配。名称相似不是依据，不得操作同机的 PLM 等其他应用。

## 增量生产发布顺序

1. 运行本次功能的定向测试、`manage.py check`、`makemigrations --check --dry-run` 和 `git diff --check`。
2. 比对**正在运行的镜像文件**与本次文件，制作显式文件清单；不要把整个脏工作区、数据库或 `.env` 上传覆盖。
3. 保存五个容器的启动配置、当前镜像 ID、业务群配置和发布清单到受限发布目录；备份文件可能含凭据，权限必须为 0700/0600，不得提交 Git 或输出内容。
4. 基于当前线上镜像制作本次增量镜像，先在临时测试库运行迁移和定向测试。保留旧镜像，不执行镜像清理。
5. 暂停五个容器，确认无后台任务写库，再对真实 SQLite 使用在线备份 API，执行 `PRAGMA integrity_check`，记录备份路径。
6. 使用新镜像执行数据库迁移；更新已有群的“推送公司”选择，不更改既有应用密钥、群 ID、报表周期和发送时间。
7. 用原有环境、挂载、端口 8001 和重启策略重建五个同名容器；保留停下来的旧容器用于回滚。
8. 核验新镜像 ID、`showmigrations`、`manage.py check`、HTTP 登录页、后台多选字段、群公司映射和定时命令 `--dry-run`；不得把 dry-run 当实际群送达。

全量首次部署的既有入口是本地 `scripts/deploy_remote.sh mesdevserver 8001`。它会上传完整源码并替换容器，不适合直接发布混有无关改动的工作区。`deploy_to_ub.sh` / `deploy_card_fix.sh` 是历史脚本，不作为当前生产发布入口。

## 钉钉共享应用与同群多公司

- 钉钉应用仅配置一次，通过“申请公司映射”关联现有 FNS / NBHH 公司。
- “钉钉群推送配置”的“推送公司”可多选；勾选哪些公司，该群就只接收哪些公司的报表。
- 同一群选择 FNS、NBHH 后，两家公司分别计算、分别生成 Excel / A2UI 卡片并发送到该群，不混算。
- 只选 NBHH 时，即使历史单公司字段保留 FNS，也不能额外推送 FNS；多选字段有值时以多选为准。
- 付款日报/周报/月报周期和发送时间沿用后台配置；空周期表示未启用付款定时推送，不擅自新增周期。
- 全量审批同步不受群公司选择影响；卡片继续使用已验证的机器人原生 A2UI 通道，不要求个人 DWS 账号。

## 线上验证

```bash
ssh mesdevserver
cd ~/deploy/daily-report
docker ps --filter name=daily-report
docker exec daily-report-web python manage.py check
docker exec daily-report-web python manage.py showmigrations integrations
docker exec daily-report-web python manage.py send_scheduled_payment_reports --dry-run
docker logs --tail 50 daily-report-web
docker logs --tail 50 daily-report-scheduler
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8001/accounts/login/
```

## 回滚

若迁移或健康检查失败：保持所有写入服务停止，核实本次发布记录中的绝对备份路径，按原路径恢复 SQLite，再恢复旧镜像和旧容器配置。恢复前另存失败现场数据库；不要在服务仍写入时覆盖数据库，也不要恢复其他项目的数据。具体旧容器名、镜像、配置快照和 SQLite 备份路径以该次发布记录为准。
