# 采购销售日报原生 A2UI 与交接包

## 本次行为
- 同一公司一张经营日报卡片，销售/采购分区展示；仅勾选销售或采购时，仅呈现所选模块。
- 卡片、PDF 和 Excel 同用过滤后的快照，不会让未勾选模块混进附件；同群多公司分别统计与投递。
- 指标包括当日金额/笔数/覆盖率、关联金额、月度日报与金蝶金额、月/年对账差额；图表为近15天趋势和当日客户/供应商金额分布。
- 原生机器人身份直接发送；不使用个人DWS、不自动降级Markdown。
- 必须准备成功PDF与XLSX，再上传两份附件、创建卡片、发送PDF与XLSX；PDF失败不以HTML冒充。
- 分阶段状态位于ReportDelivery.delivery_state；上传与渲染失败可重试，结果未知的群消息停止自动重发。

## 文件
- integrations/services/operations_a2ui.py：范围过滤、真实数据模型。
- integrations/services/a2ui_robot.py：付款/经营日报共用原生机器人发送器；payment_a2ui.py保留旧导入兼容。
- integrations/services/operations_delivery.py：三件套投递与检查点。
- integrations/migrations/0018_report_delivery_state.py：新增JSON检查点字段。
- docs/templates/operations_daily_report.a2ui.json：三帧、55组件、双业务4图表布局。
- scripts/build_report_push_kit.py：白名单脱敏打包。
- handoff/report-push-kit/README.md：其他项目接手入口；压缩包在handoff/report-push-kit-20261028.zip。

## 验证
- python manage.py test integrations core.tests.test_admin_audit --verbosity 1：127项通过。
- 官方保留JSON Schema：三帧、55组件及全部数据绑定通过；不等同于钉钉客户端实际渲染验收。
- 生产只读取FNS/NBHH真实快照，每家分别校验SALES/PURCHASE/BOTH；金额与原快照一致，Excel工作表正确，无数据库修改和群发送。
- 虚构示例生成6页PDF与销售/采购分表Excel，PDF金额文字及逐页视觉检查通过。
- 压缩包解压到独立临时目录，核验所有SHA-256并运行纯标准库离线示例，不需要项目环境、账号或网络。
- 2026-10-28 部署收尾已定位并修正邮件旧测试样例（scope → content_types、缺少内容选择），同时修复邮件配置审计仍读取已删除 scope 字段的问题。本地及服务器隔离镜像各执行全仓653项测试，全部通过。服务器对FNS/NBHH × SALES/PURCHASE/BOTH实际生成六组PDF和Excel，金额与快照一致。

## 上线边界
2026-10-28 已以 operations-a2ui-20261028-1002 完成生产增量部署，0018迁移已执行，五个容器同步更新；未额外发送新的经营日报卡片。原付款周报/月报、18:00、FNS/NBHH配置保持不变。发布及备份记录见 docs/deployments/2026-10-28-operations-a2ui.md。遵循根目录《UB端部署说明.md》确认真实生产目录和服务，保留回滚镜像与备份。原有SENT投递不重发；旧FAILED缺少阶段状态时先人工核查，避免补发造成重复。
