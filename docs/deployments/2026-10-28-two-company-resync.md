# 2026-10-28 FNS / NBHH 双公司重新同步与群推送验证

- 批次：`two-company-resync-20261028-1038`。
- 状态：已完成线上数据切换、生产库独立核对和六份真实群推送。接口回执已确认；钉钉客户端视觉效果由用户继续验证。
- 目标：`mesdevserver:/home/mesdev/deploy/daily-report`，Web 端口 8001；不操作同机 PLM。
- 现有生产镜像：`daily-report:operations-a2ui-20261028-1002`；本次不改应用镜像。

## 范围与保护

- FNS → FnsOffical / org001；NBHH → NBHHK3CLOUD / org001。不得跨账套合并其他组织。
- 客户、供应商：重新获取对应组织基础资料，按精确名称补充本地档案；保留既有档案 ID、人工映射和手工业务单据。
- 销售出库 / 采购入库：2026-01-01 至同步时点，业务日期上界为 2026-10-29（不含）；在隔离数据库更新，不直接清空线上库。
- 付款审批：共享钉钉应用按月取 2026 年实例 ID，再读取详情；仅按表单“申请公司”精确归属 FNS / NBHH，其他公司不重算。
- 旧同步记录保留用于审计；刷新结果使用新成功批次参与计算。
- 经营日报主表仍按项目原有手工业务口径；K3Cloud 用于对账，不替换主表，也不与主表重复相加。付款统计按申请创建时间，不代表实际付款流水。

## 备份

- 数据库：`/home/mesdev/deploy/daily-report/backups/pre-two-company-resync-20261028-1038.sqlite3`，SQLite integrity_check=ok。
- 历史报表和日志：`/home/mesdev/deploy/daily-report/.releases/two-company-resync-20261028-1038/prior-reports-and-logs.tar.gz`。
- 切换前再备份当前线上库，并检查业务 / 配置指纹；允许保留登录会话和 last_login，不得覆盖其他并发变更。
- 服务器发布目录 0700，含受限配置和业务数据，不提交或展示其中凭据。

## 中断原因与恢复

一次性 staging_work.py 将 save_approval 的 raw 与 instance_id 参数传反；通过生产镜像 inspect.signature 确认签名后只修正运维脚本。线上库没有切换、没有发群消息；恢复原后台服务后，再暂停后台，从付款审批阶段继续，复用已完成的 K3Cloud 隔离数据。月度 ID 和审批详情缓存支持续跑。

## 已发送的六份推送

1. FNS / NBHH：2026-10-27 经营日报，各原生 A2UI + PDF + Excel。
2. FNS / NBHH：2026-10-19—2026-10-25 付款申请周报，各 A2UI + Excel。
3. FNS / NBHH：2026-09-01—2026-09-30 付款申请月报，各 A2UI + Excel。

目标仅使用既有群配置 ID 1，保持公司选择、内容、时刻及应用凭据不变。保存持久发送账本；遇到结果不明立即停止，不盲目重试。预期 6 份报表、14 条卡片 / 文件消息。

## 并发变更保护记录

首次审批缓存完成后，生成快照时确认应使用参数 `force_regenerate=True`（不是 `force=True`），只改运维脚本。失败处理恢复后台任务后，11:04:53—11:05:02 的线上定时 K3Cloud 同步新增 SyncRun 626，更新 1,102 条出入库记录的 sync_run_id / updated_at 及 217 条映射的 updated_at，金额和行数未变。切换保护正确拒绝覆盖这次变更。

因此重新暂停后台，以最新线上数据库建立第二份备份 `/home/mesdev/deploy/daily-report/backups/pre-rebase-two-company-resync-20261028-1038.sqlite3`，重新克隆隔离库并刷新 K3Cloud；复用完整审批原始缓存，保留线上新增的 SyncRun 626。没有简单替换指纹来绕过保护。原审批完成副本保留在受限目录 `prior-approval-complete-stage.sqlite3`。

## 最终结果

### 同步数量和金额

基础资料数量为源端当前组织行数，不是新建本地档案数；旧简称、手工档案与关联保留，不能拿本地名称数直接等同 K3Cloud 编码数。金额单位：人民币元。

| 公司 | 客户源行 | 供应商源行 | 2026 销售出库单 / 金额 | 2026 采购入库单 / 金额 | 2026 付款审批 |
|---|---:|---:|---:|---:|---:|
| FNS | 197 | 962 | 3632 / 103,604,439.40 | 7336 / 62,574,304.74 | 2385 |
| NBHH | 80 | 400 | 2342 / 35,154,001.14 | 5057 / 22,400,652.62 | 931 |

- Kingdee 完整刷新 SyncRun：FNS 627、NBHH 628。
- DingTalk 完整刷新 SyncRun：FNS 629、NBHH 630；源实例 3,585，目标公司保存 3,316，其他公司 269 个源实例跳过，旧其他公司数据未改动。
- 8 条不再属于有效源单据窗口的 FNS 本地单据标记无效，不纳入新汇总；旧同步历史保留。
- 昨日 K3Cloud：FNS 销售 16 单 / 117,373.09，采购 52 单 / 372,133.17；NBHH 销售 8 单 / 74,259.39，采购 17 单 / 116,377.34。

### 付款周报 / 月报

按创建时间归入期间；总金额包含不同审批状态，不等于实际付款金额。

| 报表 | 期间 | 申请数 | 总申请金额 | 已完成 / 进行中 / 已终止 |
|---|---|---:|---:|---:|
| FNS-week | 2026-10-19—2026-10-25 | 53 | 1,216,202.76 | 26 / 26 / 1 |
| NBHH-week | 2026-10-19—2026-10-25 | 19 | 272,542.27 | 1 / 18 / 0 |
| FNS-month | 2026-09-01—2026-09-30 | 253 | 11,072,757.69 | 169 / 76 / 8 |
| NBHH-month | 2026-09-01—2026-09-30 | 86 | 3,474,382.20 | 39 / 46 / 1 |

### 真实投递及最终验证

- 发送时间：2026-10-28 11:14:06—11:14:29（Asia/Shanghai）。
- 目标：既有群推送配置 ID 1（名称“群日报定时由机器人发送”），应用 ID 1；未改目标、凭据和 18:00 定时设置。
- 6 份报表全部 SENT；6 张原生卡片的 flowStatus=FINISH，目标群 deliverResults.success=true；8 个附件（2 PDF + 6 XLSX）接口确认成功。合计 14 次 create/file 调用 ACCEPTED。
- 经营日报快照 70 / 71，投递记录 34 / 35，card / pdf / excel 均 SENT，attempt_count=1；只读模拟重复执行返回 SKIPPED，禁止构建发送客户端，未增加消息。
- 生产库切换后、恢复后台前执行独立核对：绑定、全年新批次、月/年 K3Cloud 汇总、申请公司过滤、付款数量及金额全部通过；SQLite integrity_check=ok，HTTP 200。
- 五个生产服务全部恢复；未改变镜像；无残留 staging 容器。
- 改动审计：仅目标基础资料、组织绑定、K3Cloud 单据/明细、付款审批、快照、新 SyncRun 发生变化；保留最新线上原有 626 条同步记录；手工业务单据、群配置及其他公司数据未改动。

### 需要用户验证 / 注意

- 在钉钉客户端核对六份报表的公司抬头、期间、卡片视觉与 PDF / Excel 打开情况。接口成功不等同于已人工确认客户端视觉效果。
- 2026-10-27 两家公司手工业务日报数均为 0，经营日报主表按现有口径显示 0；K3Cloud 有真实采购/销售记录，并已用于月/年对账。这不是本次同步无数据，也没有擅自把两种口径混为同一个金额。
- 运维失败日志与标记留作审计历史；最终成功证据为 staging.ok、cutover.ok、send.ok、final-verification.json。

## 证据位置

- 生产发布证据：`/home/mesdev/deploy/daily-report/.releases/two-company-resync-20261028-1038`。
- 生产发送账本：`/home/mesdev/deploy/daily-report/data/resync-validation-two-company-resync-20261028-1038/send-ledger.json`。
- 生产最终回执核对：同目录 `final-verification.json`。
- 本地非凭据证据：`E:/DEV/dailyReport/.tmp/two-company-resync-20261028-1038/summary.json`、`stage-change-audit.json`、`live-data-verification.json`、`final-verification.json`。
- 切换前最终数据库备份：`/home/mesdev/deploy/daily-report/backups/before-cutover-two-company-resync-20261028-1038.sqlite3`。
- 已真实发送消息；任何后续数据库恢复都应保留本次投递账本和回执，不得恢复后直接盲目重推。
