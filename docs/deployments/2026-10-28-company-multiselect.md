# 2026-10-28 同群多公司选择生产发布

- 服务器：mesdevserver（mesdev@172.16.77.80）。
- 项目：/home/mesdev/deploy/daily-report。
- 发布标识：company-multiselect-20261028-003955。
- 镜像：daily-report:company-multiselect-20261028-003955。
- 数据库迁移：integrations.0017_group_company_selection，已执行。
- 群配置 id=1，共享钉钉应用 id=1；推送公司为 FNS、NBHH，群 ID 未变。
- 发送时间保留 18:00；付款报表周期原为 []，本次未擅自启用，后续须在后台选择付款日报/周报/月报才会自动发送。
- scheduler 已接入 send_scheduled_payment_reports，周期未启用时不产生付款发送任务。
- 五个服务使用新镜像，登录入口 HTTP 200，后台多选页面成功渲染，重启计数均为 0。
- 本地及生产镜像隔离预检均为 61 项定向测试通过；check、makemigrations --check --dry-run 通过。
- 上周报表试生成：FNS 53 笔、NBHH 19 笔；Excel 明细按审批实例逐一验证公司，不混算。此为 dry-run，未发送任何群消息。
- 全量同步、机器人原生 A2UI、Excel 生成逻辑均与发布前镜像校验值相同；审批总数保留 391 条。
- 数据库备份：/home/mesdev/deploy/daily-report/backups/pre-company-multiselect-20261028-003955.sqlite3，integrity_check=ok。
- 发布快照、回滚容器名及最终验证：/home/mesdev/deploy/daily-report/.releases/company-multiselect-20261028-003955/verification.json。该发布目录包含受限凭据快照，不得上传代码仓库。
- 旧镜像和五个已停止的旧容器保留，不自动清理。

下次发布前先阅读项目根目录《UB端部署说明.md》。不要对本文件发布目录执行 git pull，也不要改用 /data/dailyReport 或同机 PLM 项目路径。
