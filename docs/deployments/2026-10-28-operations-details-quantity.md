# 2026-10-28 采销日报明细、数量与合计发布

## 发布状态

- 版本：operations-details-qty-20261028-r2。
- 生产目录：/home/mesdev/deploy/daily-report；报表日期：2026-10-27。
- 镜像：sha256:dd4e418275ddbe4740a8a0ef81bbb4714e8a4ee67272c77f2c617dfda8922142。
- web、mailer、backup、sync、scheduler 五服务均运行，重启次数均为 0；HTTP 登录页返回 200。
- 备份：/home/mesdev/deploy/daily-report/backups/pre-operations-details-qty-20261028-r2.sqlite3；以应用用户执行 SQLite integrity_check，结果 ok。保留原五容器以供回滚。

## 改动范围

- Excel/PDF 恢复人员日报明细；无人提交仍保留全部表头及“暂无提交记录”，不使用金蝶数据伪造人员提报。
- 金蝶明细包含当日全量有效单据、业务日期、单号、客商、数量、单位和金额；保留退货负数。
- 明细末行汇总数量、金额；数量最多显示六位小数。混合单位仅作源记录算术求和，明确注明未折算，不代表统一实物数量。
- 人员日报无单位字段时注明未记录单位；旧快照缺数量时不补零。
- Excel 单号列宽 38，PDF 单号列加宽且禁止换行；PDF 保持书册版式。
- 保留采销合并汇总、金蝶近十五日趋势、当月双线图及手工口径月度对比 sheet；不恢复月度/年度对账差额。
- 仅发布 manifest 内六个文件；不提交 Git，不改动其他业务功能。

## 验证

- 发布镜像隔离数据库、禁网完整测试：665 项通过（149.463 秒）。
- 六组预检（两公司 × BOTH/SALES/PURCHASE）通过，数量和金额与源 SQL 核对。
- 正式快照 ID 70、71 保持不变，更新前快照及投递账本保存于生产 data/operations-details-qty-final-20261028-r2。
- 正式生成在 network none 一次性容器执行，额外 mock 禁止构造钉钉客户端和发送请求；投递账本逐字段未变，已发送入口返回 SKIPPED，本轮发送 0 条。
- Excel 六个 sheet、空表头、数量/金额数值类型及合计、单号禁换行均通过；PDF 文本、页数、末页合计及 SHA256 通过，两公司全部页面已渲染目视检查。

| 公司 | 单据数 | 数量算术合计（混合单位未折算） | 金额合计（元） | PDF 页数 |
| --- | ---: | ---: | ---: | ---: |
| FNS | 70 | 567431.08 | 513094.31 | 9 |
| NBHH | 25 | 291483 | 190636.73 | 7 |

## 数据变化说明

生产源记录已不同于早期预检摘要，不能继续硬编码早期金额及单据笔数。正式验证按当前有效源记录动态核对，不通过金额钉死来制造不变结果。FNS 当日实际为 52 笔采购与 18 笔销售，共 70 笔；NBHH 为 17 笔采购与 8 笔销售，共 25 笔。

| 公司 | 截至 10/27 当月采购金额 | 截至 10/27 当月销售金额 | 采购/销售（%） |
| --- | ---: | ---: | ---: |
| FNS | 5374144.42000000000 | 7806278.570000000 | 68.8439 |
| NBHH | 2472032.2900000000 | 3551750.58000000000 | 69.6004 |

## 本地证据

- E:/DEV/dailyReport/.tmp/operations-details-qty-20261028-r2/final-artifacts/verification.json
- E:/DEV/dailyReport/.tmp/operations-details-qty-20261028-r2/final-artifacts/local-verification.json
- E:/DEV/dailyReport/.tmp/operations-details-qty-20261028-r2/final-artifacts/health-verification.json
- 同目录 FNS-BOTH、NBHH-BOTH 的 PDF/Excel 与全部页面 PNG。

本轮未触发全量重新同步、付款报告推送或日报补发；不影响同机 PLM。
