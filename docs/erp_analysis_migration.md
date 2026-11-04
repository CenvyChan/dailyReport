# 经营分析移植说明

移植来源：项目根目录的 \mes-erp-analysis-port（2026-11-04）。

## 已接入的功能

入口：登录后进入「分析 → 经营分析」，路径为 /reports/erp-analysis/。

- 六类分析：采购执行、应收欠款、库存健康度、销售漏斗、生产执行、委外经营。
- 选择分析结束月份，默认取截至该月的近 12 个月。任务保存 window_months；单月试运行可显式指定 1 个月，不改变定时调度的近 12 个月口径。
- 持久化后台任务、单份报告独立结果、页面进度轮询、历史任务。
- 自包含 HTML 报告、静态 SVG 趋势、排行与明细；ZIP 内包含成功报告的 HTML / JSON 及 manifest.json。
- 公司级月度调度、定时任务幂等、钉钉完成/失败入口通知（ZIP 文件名 + 各项分析内容）。
- 管理页面公司隔离：只有该公司的管理员或 report_viewer 可访问页面、结果和下载；未授权公司任务返回 404。按本项目已有日报方式提供 30 天签名快照，签名同时绑定任务与公司，非法/过期链接不能访问。
- 每份报告的失败或未购买模块分别显示，部分成功状态为 PARTIAL。失败不伪装成零数据。

本次没有替换原有经营日报、采销对比、Excel/PDF 输出或旧推送配置。

## Admin 配置月度推送

打开「集成 → 经营分析调度 → 增加」：

1. 公司：选择 FNS（飞诺斯），不要用金蝶账套名代替公司。
2. 启用月度分析：勾选后才自动运行，不勾选仅保存配置。
3. 每月运行日、运行小时：例如 1 日、8 时（北京时间），每月生成截至上个月末的近 12 个月报告。运行日为 1–28；服务恢复后本月尚未触发的到期任务会补触发。
4. 分析种类：勾选需要的分析，至少一项。仅采购执行可只勾「采购执行分析」。
5. 通知群：选择已授权给本公司的启用钉钉群；群的推送公司与应用公司映射必须包含 FNS，应用还须设置机器人 Code。留空则只生成，不推送。
6. 保存。一家公司只允许一份调度配置，同公司同分析月份定时任务只生成/通知一次。

通知标题含「ZIP」，正文含各报告分析内容和结果。点击可预览及下载 ZIP；ZIP 内为 HTML 报告、JSON 明细和生成清单，并非旧日报 Excel/PDF 附件。无需配置互动卡片模板。

## 启用步骤

开发测试使用隔离数据库。生产迁移、独立工作服务和只读试运行的部署记录另见 docs/deployments/2026-11-04-erp-analysis.md；默认不自动启用任何公司的推送。

在项目已有 Python 运行环境中执行：

~~~sh
python manage.py migrate
python manage.py collectstatic --noinput
~~~

本次新增迁移为 integrations/0024_erp_analysis，创建经营分析调度与任务两张表，不回写原有经营数据。

1. 在集成配置中确认当前公司存在启用的 KingdeeOrgBinding 和 KingdeeAccount。
2. 组织编码保持原始前导零；由 ORG_Organizations 查唯一 FORGID，不把编码猜成内部 ID。
3. 启动后台工作进程：

~~~sh
python manage.py run_erp_analysis --watch
~~~

这是前台管理命令，生产环境由独立的 daily-report-erp-analysis 容器托管，并只运行 **一个** 经营分析工作进程。Docker Compose 中已增加 erp-analysis 服务。每 60 秒检查到期调度并处理持久化队列。也可由系统定时器每分钟调用一次不带 --watch 的命令，但不要与持续工作进程并行运行。

4. 手动进入经营分析页提交任务；页面只入队，不在网页请求里执行长时间 ERP 查询。
5. 月度自动分析：进入后台「经营分析调度」，选择公司、分析种类、运行日（1–28）、小时。到期生成上个月的报告，遗漏运行后会在本月补触发。默认不启用。
6. 钉钉通知：可选授权给本公司的启用群与应用，配置机器人 Code 和 PUBLIC_BASE_URL。发送原系统支持的 sampleLink，标题明确标注「经营分析 ZIP」，正文列出 ZIP 文件名、分析期间、每一项分析的名称/生成状态/分析内容。点击进入 30 天有效的签名快照，可直接阅读并下载 ZIP。链接持有者即可访问，请勿对外转发；不另建凭据、不自动向原有日报群广播。

同公司同分析月份的定时任务只创建一次；手动生成允许同期间重复导出。

## 中断与失败

- 任务状态：PENDING → RUNNING → SUCCESS / PARTIAL / FAILED。
- 每完成一份报告即保存结果；任务之间不共享金蝶 SDK 会话实例。
- 单据查询累计或任一页触及 10000 行、游标停滞、已知 RowCount 不完整、字段列数不一致、无 Rows 错误信封均为失败，不静默累计。
- 单据按月分片；采购采用半开区间，生产/委外采用闭区间 BETWEEN。
- 系统报表按实际原始行数推进游标，最多等待单次查询 300 秒。
- 工作进程被中断留下 RUNNING 时，**先确认原进程已停止**，再显式恢复：

~~~sh
python manage.py run_erp_analysis --recover-task 123
~~~

恢复会保留已成功报告，只重跑未完成报告；该命令还会处理其他排队任务。

- 通知状态独立于生成状态。推送异常不改报告状态、不重生成、不自动重发失败通知。
- 不确定发送是否成功时先到钉钉群确认；确实未送达后才执行：

~~~sh
python manage.py run_erp_analysis --retry-notifications
~~~

该命令只重试失败通知，不重新取数。它会重试全部失败通知，请逐项确认后使用。

## 六份内容与来源

| 报告 | 原数据源 | 保留的核心内容 |
| --- | --- | --- |
| 采购执行 | PUR_PurchaseOrderDetailRpt + PUR_PurchaseOrder | 金额结算、月度趋势、供应商/物料/组织排行、逾期未收、独立分录交付分布与欠交、TOP 50 样本集中度 |
| 应收欠款 | AR_receivable 表头 + 收款计划 | 单号去重、重复计划去重、客户欠款、月度应收与计划总额核对 |
| 库存健康度 | HS_INOUTSTOCKSUMMARYRPT，每月一份 | 最新有效期末、共同期间分母、7 档覆盖分层、滞压、直发排除后的短缺、缺价/数量/金额平衡质量信号 |
| 销售漏斗 | SAL_OutStockInvoiceRpt | 出库—应收—实收、整体与分组不同分母、客户/业务员排行、负未结算保留 |
| 生产执行 | PRD_MO + PRD_MORPT | 完工、状态、实际工期与样本数、车间/物料排行、逾期/积压、质量及单据类型占比 |
| 委外经营 | SUB_SUBREQORDER + SUB_PickMtrl + SUB_PPBOM | 委外执行与交付、申请/实领/少领、当前在制、良品退料、负值和平衡式质量信号 |

原 FieldKeys / FormId / FilterString 从移植包 Normalizer 提取到 integrations/services/erp_analysis/fields.py，运行时不再依赖移植包文件夹。

## 口径边界与必要适配

- 金额与数量按 ERP 原字段计算；不自动换汇、不把各模块的含税/本位币口径强行统一。
- 采购金额来自展开报表，交付分布来自单据分录，不能从报表行数计算订单分录交付率。
- 采购未结算逐行截零；销售和委外在制负值原样保留。
- 供应商集中度沿用原包「未结算排行 TOP 50」样本范围和顺序，不是全体供应商采购金额集中度。
- 应收无到期日字段，不输出账龄或逾期认定。收款计划为查询时当前状态，并非历史月末余额。
- 生产/委外执行字段同样来自当前查询状态；参照日期固定为分析月份的次月首日，但不声称重建了历史业务状态。
- 库存正文明确展示实际有数据的首期、末期，末月无数据不会冒充末月库存。
- SUB_PPBOM 没有 FDate；在制为生成时当前快照。平衡式包含良品退料，不能重算覆盖 ERP 原值。
- 委外没有实际开工日期，不把「计划开工到完工」称为真实加工周期，不输出无依据的金额。
- 原包写死的 2025-07-31 期初批次和某家关联方名称是原账套专有信息，**没有用于本项目的期初/关联方认定**。本项目完整单据计算明细仍保存在 JSON 中。
- 目标项目无站内信服务，本次以受保护的任务历史与进度页承接手动任务结果；钉钉复用现有应用机器人。
- 数值格式损坏、NaN、Infinity 会显式失败，而非像原包数值兜底逻辑那样静默当零。不可识别日期在报告中提示并留在「未识别」月度桶。

## 实现位置

- integrations/services/erp_analysis/：目录、查询、正常化、纯计算、HTML 趋势、任务和通知编排。
- integrations/models.py 与 migrations/0024_erp_analysis.py：持久化队列与调度。
- integrations/management/commands/run_erp_analysis.py：后台工作入口。
- reports/views_erp_analysis.py、reports/erp_analysis_permissions.py、reports/urls.py：页面与公司授权。
- templates/reports/erp_analysis*.html、static/css/erp-analysis.css、static/js/erp-analysis.js：页面与离线报告。
- integrations/tests/test_erp_analysis*.py：指标、协议、组织参数、公司隔离、任务、归档、恢复和通知测试。

## 验证

~~~sh
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test integrations.tests.test_erp_analysis integrations.tests.test_erp_analysis_metrics
python manage.py test
~~~

浏览器验证使用单独的临时 SQLite 和明确标注的虚构数据，验证六份报告趋势/章节、390px 手机布局、明暗主题、后台入队和 ZIP 下载；不调用真实金蝶或钉钉接口。

上线前仍需使用本公司真实账套进行只读取数与财务口径核验，尤其核算体系/会计政策默认编码、多币种、组织授权和模块购买情况。不能把单元测试或虚构数据验证视为真实业务数值已经对账。

### 本次已完成的验证（2026-11-04）

- 新增经营分析测试 46 项通过；全项目 771 项测试通过。
- Django 配置检查通过，makemigrations --check --dry-run 无遗漏迁移。
- 新增 Python 代码 Ruff 检查通过；git diff --check 通过。
- 浏览器实测：6 份报告均有趋势图及业务章节；390px 视口无页面级横向溢出；明暗主题、任务入队、真实 ZIP 下载通过。
- 全仓库原有 3 条 Ruff 提示仍存在（旧 DingtalkGroupForm 的 DJ007 / DJ006，PaymentReportDispatch 的 DJ008）；与 HEAD 基线对比确认不是本次新增，未改动相关旧逻辑。
