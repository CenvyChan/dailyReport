# 2026-10-28 经营日报 A2UI 增量发布

- 发布标识：operations-a2ui-20261028-1002。
- 目标：mesdevserver:/home/mesdev/deploy/daily-report；Web 入口端口 8001。
- 范围：经营日报原生 A2UI + PDF + Excel、分步投递检查点、0018 迁移；修复邮件配置审计仍使用已移除 scope 字段的问题。
- 本地及服务器隔离镜像各执行 653 项测试，全部通过；修正旧邮件测试样例到 content_types，测试环境补齐 requirements.txt 中已锁定的 waitress==3.0.0，不修改邮件发送业务规则。
- 服务器使用生产数据库的隔离副本，验证 FNS/NBHH × SALES/PURCHASE/BOTH 六组真实快照；原生卡片金额与快照一致，PDF 和 Excel 实际生成成功。预检无业务写入、无群消息。
- 从线上 Web 精确镜像构建，仅包含 manifest.json 明确列出的 14 个文件；未上传 .env 或业务数据库，原 core/admin.py 热修复保留。
- 发布流程：停止五个写入服务、SQLite 在线备份和完整性校验、0018 迁移、保留旧容器、复用原环境/命令/挂载/端口/重启策略重建。
- 服务端发布证据：/home/mesdev/deploy/daily-report/.releases/operations-a2ui-20261028-1002。该目录含受限环境快照，不得提交仓库或展示凭据。
- 部署结果：0018 迁移和 delivery_state 字段已确认；五个容器全部使用镜像 sha256:08204a4ea766c073fd17d06bda3b1af7d1e989141caa4a2009fd82117ec95efa，运行正常且重启计数为 0；8001 登录页 HTTP 200；14 个发布文件哈希逐项匹配。
- FNS/NBHH 的历史 SENT 日报实测返回 SKIPPED，未创建客户端或发送消息；付款调度 dry-run 正常。
- 原环境变量、启动命令、挂载、端口、重启策略、业务记录数量和群配置逐项保持一致：FNS + NBHH，week + month，18:00。
- SQLite 备份：/home/mesdev/deploy/daily-report/backups/pre-operations-a2ui-20261028-1002.sqlite3，integrity_check=ok；旧容器名为原名加 -rollback-operations-a2ui-20261028-1002。回滚需停止全部写入服务后恢复数据库与对应旧容器，按受限发布目录记录执行。
- 首次新布局真实群发送和钉钉客户端显示仍需验收；本轮不强制重发历史已发送日报，也不使用未确认测试群。

## 首轮调度观察

- 2026-10-28 10:17:52（Asia/Shanghai），新 scheduler 已完成首轮检查，FNS/NBHH 的 2026-10-27 快照均完整，因未到 18:00 未发送；没有手工提前发卡。其他公司的同步/快照处理按既有范围保留，未增加未勾选公司的群推送。
- 10:18 再核验五个容器运行正常、重启计数为 0，manage.py check 无问题。历史日志中的其他公司不完整快照提示不属于本次部署异常，未更改其数据。
