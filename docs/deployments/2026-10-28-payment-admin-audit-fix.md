# 2026-10-28 钉钉群配置保存失败热修复

- 生产目录：mesdevserver:/home/mesdev/deploy/daily-report；发布标识：payment-admin-audit-20261028-010107。
- 现象：勾选付款周报、月报并保存时返回系统错误，事务回滚。
- 日志根因：TypeError: Object of type Company is not JSON serializable。多选公司通过 model_to_dict 产生模型对象列表，审计快照原先只转换顶层对象。
- 修复：core/admin.py 的 _json_value 递归处理列表、元组和字典，将公司对象转换为主键。未改变报表计算、同步范围和调度规则。
- 回归：新增实际后台 POST 保存测试，覆盖已有多选配置保存周报/月报，以及修改公司后连续保存。此前两个测试均复现同款异常；修复后 65 项审计及付款定向测试全部通过。
- 生产预检：以备份数据库的隔离副本执行后台 POST，返回 302，周报/月报及 FNS、NBHH 公司选择保存成功，审计记录成功；未向钉钉发送消息。
- 部署：基于当前线上镜像仅加入 core/admin.py 与审计测试文件，只替换 daily-report-web；其余四个容器 ID 保持不变。环境变量、数据挂载、8001 端口保留；登录页 HTTP 200，manage.py check 通过，重启计数 0。
- 数据保护：备份位于 /home/mesdev/deploy/daily-report/backups/pre-payment-admin-audit-20261028-010107.sqlite3；旧后台容器 daily-report-web-rollback-payment-admin-audit-20261028-010107 保留。热修复不直接修改付款周期，请在页面重新保存已选择的周期。
- 证据：/home/mesdev/deploy/daily-report/.releases/payment-admin-audit-20261028-010107/deployed.ok、tests.log、save-probe.log。该目录含受限环境快照，不得提交仓库或向用户展示凭据。
- 发布验收补充：涉及后台多选的变更，必须覆盖已存在关联数据的实际 POST 保存与事务提交；仅验证页面渲染或 ModelForm.is_valid 不足以证明可保存。
