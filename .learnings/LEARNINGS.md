# Learnings 
 
Corrections and best practices captured during development.

## [2026-10-27] 子代理模型与推理强度偏好

- Category: correction
- 用户要求需要拉起子代理时优先指定 `gpt-6.1-sol`，推理强度设为 `low`（轻度）；仅在对应代理角色允许模型覆盖时使用，角色限制优先。

## [2026-10-27] 卡片发送身份与传输通道分离

- Category: correction
- 用户要解决的是使用应用机器人身份发送 A2UI 卡片，不是固定个人 dws 登录账号。不得把现有 dws 实现路径误当成协议硬性要求，也不得以固定服务账号作为未经确认的替代需求。
- 先核对官方机器人接口是否支持原生 A2UI；区分普通模板互动卡片与 A2UI，不承诺兼容或擅自降级版式。

## [2026-10-27] 不把 DWS 适配器限制误当成钉钉原生 API 限制

- Category: correction
- 官方 Python SDK alibabacloud-dingtalk 2.2.65 的 card_1_0 提供 CreateAndDeliverAICard / UpdateAICard，包含原生 a2uiMessages 和群投递 robotCode。
- 先前仅依据 DWS 适配器文档推断机器人 A2UI 不可用，证据不足；应搜索官方完整 SDK，包括名称中的 AICard，而不是仅检索模板卡片 CreateAndDeliver。
- 使用当前部署应用 Token 向原生接口提交无目标、无内容的空对象，收到 MissingoutTrackId，证明到达参数校验；这不等于权限、完整投递、发送身份和渲染已验证。
- 不以无效参数探测或 SDK validate 通过冒充真实发卡成功；获得测试群后再验证完整链路。


## [LRN-20261028-DEPLOY] correction
- Logged: 2026-10-28
- Priority: high
- Status: promoted
- Area: infra
- 用户确认生产项目为 `mesdevserver:~/deploy/daily-report`，不是 `/data/dailyReport`。生产为文件发布目录，没有 Git 仓库，也没有 Compose 插件；五个服务由 Docker 容器直接运行，对外 8001。
- SSH 优先使用 Git Bash `/usr/bin/ssh`；旧 Windows OpenSSH 在管道环境可能认证成功但退出挂起，不能据此判断服务器不可达。
- 已提升至 `UB端部署说明.md`，发布前先核对运行镜像与容器，不覆盖生产 `.env`、数据库或部署同机其他项目。


## [LRN-20261028-AUD] 后台多选发布须验证实际保存

**Logged**: 2026-10-28T09:05:00+08:00
**Priority**: high
**Status**: resolved
**Area**: tests

### Summary
钉钉群配置已有多选公司时，model_to_dict 返回 Company 对象列表，顶层审计序列化不足导致保存事务回滚。此前页面渲染和表单校验未覆盖该链路。

### Suggested Action
审计快照递归转换容器内模型对象；后台多选功能验收须使用已有关联数据执行真实 POST，验证重定向、持久化和审计记录。生产预检使用隔离备份副本，避免误改配置或触发业务推送。

### Metadata
- Source: user_feedback
- Related Files: core/admin.py, core/tests/test_admin_audit.py
- Pattern-Key: admin.m2m-audit-serialization

### Resolution
- **Resolved**: 2026-10-28
- **Notes**: 两个失败复现转绿；65 项定向测试及生产副本 POST 通过；仅部署后台服务，其他四个容器不动。


## [LRN-20261028-OPS] 经营日报卡片与附件统一范围并分阶段防重

**Logged**: 2026-10-28
**Priority**: high
**Status**: resolved
**Area**: backend

### Summary
经营日报原钉钉链路只推Markdown与PDF/HTML，没有实际发送Excel；BOTH快照需要按群content_types过滤所有载体，不能只过滤卡片。A2UI成功后附件超时必须持久化各自状态，禁止自动整套重发。

### Details
- 公共Chart类型是lineChart/histogram，不是line；Loop内部相对绑定须逐项校验。
- 先渲染并上传PDF/Excel，再创建原生卡片；严校目标群spaceId而非openSpaceId。
- 多公司与业务范围隔离应测试卡片、PDF源HTML、真实Excel工作表，覆盖取消勾选和历史更正。
- 保留首次发送的原始A2UI帧与回执，补附件时不重新覆盖卡片证据。
- 交接包只白名单源码、脱敏地址、虚构样例；独立目录解压运行并逐项核验SHA-256。

### Metadata
- Related Files: integrations/services/operations_a2ui.py, integrations/services/operations_delivery.py, scripts/build_report_push_kit.py
- Pattern-Key: reporting.a2ui-attachment-checkpoints


## [LRN-20261028-NOTIFY] Removed mailing-list scope must be reflected in fixtures and audit snapshots

- Status: resolved
- Root cause: MailingList moved to content_types, while old tests omitted content selection or referenced MailingList.Scope; notifications.views._snapshot still read mailing_list.scope and broke successful create/update audit recording.
- Fix: explicit content_types in relevant mail test fixtures, purchase-only content selection, audit snapshot uses content_types, and create-flow test asserts persisted audit data. No production mailing-list selections auto-filled.
- Verification: 653 tests pass locally and in isolated production image; deployed operations-a2ui-20261028-1002 with 0018 migration, six real PDF/XLSX render checks, original group configuration preserved.
- Pattern-Key: schema.removed-field-audit-fixture-drift


## [LRN-20261028-REPORT-DETAILS] correction

**Logged**: 2026-10-28T13:10:00+08:00
**Priority**: high
**Status**: resolved
**Area**: backend

### Summary
用户要求去掉对账差额、合并采销汇总，不代表允许删除日报提交列、实际明细或原版 PDF 书册结构。

### Details
上一轮以摘要重建 Excel/PDF，丢掉人员日报的客户/供应商、提报人、日期、金额列；空数据时连表头也未保留。用户明确指出 Excel 与 PDF 均不符合原版明细要求。根因是把指标级改动扩大成文档结构替换，测试仅检查新指标，未检查原有必需字段。

### Resolution
恢复原版书册式封面、总览、趋势、销售/采购日报明细账簿；空提交仍保留表头并写“暂无提交记录”。Excel 恢复统一日报提交明细，另列完整当日金蝶单据，不把 K3 当作人员提报。新增空表头、真实提交快照冻结、负数、公司/有效状态/业务日过滤、单业务隔离、超过100笔不截断、旧快照缺明细提示共6项回归。

### Metadata
- Source: user_feedback
- Related Files: integrations/services/snapshot_export.py, templates/integrations/report_snapshot_book.html, integrations/tests/test_operations_details.py
- Pattern-Key: reports.preserve-empty-schema-and-original-detail
