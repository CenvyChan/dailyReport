# 2026-10-28 采销汇总日报改版

状态：**已发布，生产验收通过；本轮未向钉钉重新发送消息。**

## 用户需求与口径

1. 移除月度／年度对账差额等展示指标，采购和销售合并为一份汇总日报。
2. 近 15 天趋势采用金蝶有效采购入库、销售出库数据，按业务日期补齐无单据日期；退货保留负数。
3. 增加当月采销双折线图。HTML／PDF 和 Excel 隐藏横轴日期标签；钉钉原生图保留真实日期点，使用公开 Chart 的 type 字段区分系列。
4. 【当月采购日报合计】【当月销售日报合计】均为金蝶报表月 1 日至报表日合计；【合计占比】= 采购 ÷ 销售，销售为 0 时显示 —／空，不代表利润率。
5. Excel 增加【采购入库金额与销售金额对比表】sheet，复用现有原表完整报表月份的手工录入／历史导入数据，明确标注来源，不与金蝶混算。当前两家公司原表 2026 年 10 月无金额数据，按原表显示 0。

## 实现与数据边界

- operations_summary 服务只读有效 StockTransaction；不更改同步记录、采购／销售手工业务、客户供应商或付款审批。
- operations 与 monthly_comparison 冻结入 ReportSnapshot；卡片／PDF／Excel 均读取快照，导出无需查询实时业务。
- 保留原对账页面及底层对账服务，不改与本次需求无关的功能。
- Excel 共四个 sheet：采销汇总、当月金蝶采销、近15天金蝶趋势、采购入库金额与销售金额对比表。

## 验证结果

- 本地完整回归：657 项通过；设置 PYTHONPATH 以让测试子进程继承隔离依赖。
- 新生产镜像隔离完整回归：657 项通过；migrate、check、makemigrations --check 通过。
- 两家公司 × BOTH／SALES／PURCHASE 六组真实数据导出；K3 月度合计与 SQL 核对，原表月度 sheet 与 monthly_comparison 核对，单业务范围不泄漏另一业务数据。
- A2UI Schema、全部绑定通过：3 帧、32 组件、2 张原生折线图。本轮未真实发卡，不将 Schema 验证表述为钉钉客户端人工视觉验收。
- 发布后实际 PDF 再次下载核验，两家公司各 1 页，指标文字正常、无月度／年度对账差额；已目视核对布局。
- 已更新两家公司 2026-10-27 快照，原 ID 70／71 不变。全部 ReportDelivery 字段前后完全一致。
- 对已 SENT 投递调用防重入口，均 SKIPPED；钉钉客户端构建及 post 均被 mock 禁止，调用次数为 0；验收容器 network=none，消息发送数 0。

### 报表月 2026-10，截至 2026-10-27

| 公司 | 金蝶采购月合计 | 金蝶销售月合计 | 采购／销售 |
| --- | ---: | ---: | ---: |
| FNS | 5,374,145.90 | 7,782,690.52 | 69.05% |
| NBHH | 2,472,032.29 | 3,551,750.58 | 69.60% |

## 发布与回滚证据

- Release：operations-summary-20261028-1205。
- 镜像：daily-report:operations-summary-20261028-1205。
- 镜像 ID：sha256:048378a6646e2991298577fd19931e9bcfb95fda482502d211b1d58963e69e4f。
- 基础镜像：sha256:08204a4ea766c073fd17d06bda3b1af7d1e989141caa4a2009fd82117ec95efa。
- 生产目录：/home/mesdev/deploy/daily-report，Web 端口 8001。
- 发布前 SQLite 备份：/home/mesdev/deploy/daily-report/backups/pre-operations-summary-20261028-1205.sqlite3，PRAGMA integrity_check=ok。
- 仅替换 manifest 中 11 个文件；本地源码与已部署 manifest 的 SHA256 全部一致。
- web／mailer／backup／sync／scheduler 五个容器均运行新镜像，RestartCount=0；HTTP 登录页 200。
- 原容器保留为各自名称加 -rollback-operations-summary-20261028-1205。
- 原环境变量、挂载、端口、启动命令、重启策略、群配置保持不变；未操作同机 PLM。
- 远程证据目录：/home/mesdev/deploy/daily-report/.releases/operations-summary-20261028-1205。
  - preflight.ok、preflight-runner.log：隔离预检。
  - deployed.ok、deploy.log：发布和备份。
  - final-probe.log、health-final.json：生产快照与服务验收。
  - final-artifacts/：最终 PDF、XLSX、HTML、verification.json。
- 生产受限数据证据：/home/mesdev/deploy/daily-report/data/operations-summary-final-20261028-1205，含快照变更前副本、投递账本前后副本和导出文件。
- 本地最终样张：E:/DEV/dailyReport/.tmp/operations-summary-20261028-1205/final-artifacts。

注意：远程发布目录包含受限配置，不展示 .env 或完整 docker inspect；既有群消息及旧附件不自动替换。本轮未重跑此前同步／付款审批／验证群推送。
