# 付款审批按“申请公司”拆分组织

付款审批的业务归属以表单字段 **申请公司** 为准。来源钉钉应用可由多个项目组织共享，无须复制 AppKey/AppSecret。后台“钉钉申请公司映射”将表单原值关联到项目组织；名称不同的历史别名也可显式映射到同一组织。

- 所有同步入口使用列表接口返回的审批实例 ID，表单统一保存为字段字典；报表兼容历史字典和组件数组。
- 各公司分别生成卡片和 Excel。Excel 汇总页写明申请公司，卡片和附件的笔数、金额取同一份公司数据。钉钉应用只需配置一次；同一群配置可在“推送公司”中多选公司，所选公司会分别生成报表并发送到同一个群聊。
- 付款日报统计前一自然日；周报统计上一完整自然周，周一推送；月报统计上月，每月 1 日推送。时间边界使用项目时区。
- 申请公司未映射、为空或未启用时拒绝混入来源公司。没有申请公司字段、也未配置映射的旧模板保持原归属。
- 新建组织不会自动授予用户访问权限，也不会猜测收件群。公司授权仍在项目原有公司授权配置中维护。

当前报表仅生成并调度 FNS（慈溪飞诺斯电子科技有限公司）和 NBHH（宁波汇慧电子有限公司）。这两个法定表单名按公司代码关联现有项目公司；不因项目公司使用简称而新建重复公司。同步仍拉取全部申请公司的数据，不使用报表白名单过滤。

## 部署与只读审计

以下命令在服务器项目目录执行。暂停自动写入与推送，避免重分类期间生成不完整报表：

```bash
docker compose stop scheduler sync mailer
docker compose up -d --build web
docker exec daily-report-web python manage.py migrate
docker exec daily-report-web python manage.py shell -c "from integrations.models import DingtalkApp; print(list(DingtalkApp.objects.values('id','name','company__name','is_active')))"
```

从输出中找到付款审批来源应用 ID，设置 APP_ID。先查看本地已同步数据，默认不修改数据库：

```bash
APP_ID=1  # 替换为上一步实际应用 ID
docker exec daily-report-web python manage.py reconcile_payment_organizations --app-id "$APP_ID"
```

输出各申请公司的笔数、金额及缺少申请公司的记录数。请核对各申请公司的统计及现有项目组织映射；同步公司数不限制为两家，但报表只推送上述两家。不要把同一组织的简称和全称盲目建成两家公司。已有组织可先在后台维护映射。

## 备份、重分类与重新同步

仅使用现有原始审批数据修复归属与表单格式：

```bash
docker exec daily-report-web python manage.py reconcile_payment_organizations --app-id "$APP_ID" --apply --create-missing
```

--create-missing 只为其他尚无同名项目组织且尚未映射的申请公司新建组织，代码按名称生成稳定哈希；FNS/NBHH 必须使用现有对应代码的组织，缺失或停用时会拒绝修复，不创建替代公司。不要把示例代码当成实际组织代码。可在后台改成团队约定的代码。

要重新从钉钉同步，必须明确起止日期。下面日期仅演示当前月范围；若有更早的错误记录，应将起日改为实际历史起日。先只读预览，再执行同一范围：

```bash
docker exec daily-report-web python manage.py reconcile_payment_organizations --app-id "$APP_ID" --refresh --start 2026-10-01 --end 2026-10-27
docker exec daily-report-web python manage.py reconcile_payment_organizations --app-id "$APP_ID" --refresh --start 2026-10-01 --end 2026-10-27 --apply --create-missing
```

写入前保存完整 SQLite 数据库备份及审批/组织/映射 JSON，路径打印在输出中，位于持久化的 backups 目录。写入在一个事务中执行，任一失败全部回滚。若出现缺少申请公司，整次修改停止，需先核对源表单。

只合并同一来源应用/模板内、由服务端明确给出实例 ID 与 business_id 对应关系的重复记录；同额同收款人不是去重依据。重复行详情保留 updated_at 最近同步的一份，避免旧状态覆盖新审批状态。重新同步范围以外的记录和源端未返回的记录不会被批量删除。完整回滚请停止所有写入服务后恢复该次 SQLite 备份；JSON 可用于审查和恢复原审批行，不能替代完整数据库回滚。

## 群与定时推送

在后台“钉钉群推送配置”中配置同一个目标群：

1. 推送公司：可多选 FNS、NBHH；只推送勾选的公司，多选优先于历史单公司字段。
2. 钉钉应用：同一个来源应用只配置一次，通过申请公司映射关联所选公司。
3. 群 ID：使用当前目标群；两家公司分别计算并发送卡片和 Excel 到同一群。
4. 付款报表周期和发送时间：沿用现有配置；全量审批同步不受勾选公司限制。

生产位置：`mesdevserver:~/deploy/daily-report`，部署步骤见项目根目录 `UB端部署说明.md`。

```bash
docker exec daily-report-web python manage.py send_scheduled_payment_reports --dry-run
docker exec daily-report-web python manage.py send_payment_report day --company FNS --base-date 2026-10-27 --dry-run
docker exec daily-report-web python manage.py send_payment_report week --company FNS --base-date 2026-10-27 --dry-run
```

NBHH 使用同一命令并将 FNS 改为 NBHH；不支持其他公司代码生成付款报表。生成文件位于 data/payment_reports。核对每家卡片和 Excel 的公司名、笔数及总金额后，再手动发送或恢复定时服务：

```bash
docker compose up -d sync scheduler mailer
```

每个群、报表周期和发送日都有独立投递记录。重复调度不会重复发送。发送失败或中断后不自动重发，以免卡片已送达而附件失败时刷出重复卡片；先核对 data/payment_reports 下的卡片回执及后台投递记录，再用 send_payment_report 指定组织和群补发。

## 发送身份

默认 A2UI 与 Excel 均以配置应用的机器人身份发送。A2UI 通过原生 createAndDeliver 接口单次提交 FINISH，不需要 dws 或个人账号。2026-10-27 已完成 FNS 群无业务数据实测，用户确认身份和版式正常。NBHH 若没有独立群配置则不发送，不复用 FNS 群。
