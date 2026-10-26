# 钉钉付款申请周报/月报功能

## 快速开始

### 1. 安装依赖
```bash
pip install -r requirements.txt  # openpyxl已包含
```

### 2. 配置钉钉
在Django Admin中配置:
- **钉钉应用**: `integrations.DingtalkApp`
- **审批模板**: `integrations.DingtalkProcessConfig`

### 3. 同步数据
```bash
# 首次同步(回看30天)
python manage.py sync_payment_approvals --lookback-days 30

# 每日同步(建议定时任务20:00执行)
python manage.py sync_payment_approvals
```

### 4. 测试报表
```bash
# 交互式测试
python scripts/test_payment_report.py

# 命令行测试
python manage.py send_payment_report week --dry-run --output-dir ./reports
```

### 5. 发送报表
```bash
# 周报(需要群ID)
python manage.py send_payment_report week --group-id <openConversationId>

# 月报
python manage.py send_payment_report month --group-id <openConversationId>
```

## 文件清单

### 核心服务
- `integrations/services/payment_report.py` - 数据汇总与分析
- `integrations/services/payment_excel.py` - Excel报表生成
- `integrations/services/payment_message.py` - 钉钉消息构建
- `integrations/services/payment_changes.py` - 变更追踪与识别

### 管理命令
- `integrations/management/commands/sync_payment_approvals.py` - 增强同步命令
- `integrations/management/commands/send_payment_report.py` - 报表发送命令

### 文档
- `docs/payment_report_guide.md` - 详细使用指南
- `docs/payment_report_integration.md` - 集成说明
- `docs/payment_report_technical_summary.md` - 技术总结
- `docs/README_payment_report.md` - 本文件

### 测试
- `integrations/tests/test_payment_report.py` - 单元测试
- `scripts/test_payment_report.py` - 快速测试脚本

## 功能特性

### ✅ 数据同步
- 增量同步(按lookback_days回看)
- 状态变更追踪(RUNNING→COMPLETED等)
- 金额变更追踪(审批修改监控)
- 幂等性支持

### ✅ 报表生成
- 周报/月报自动汇总
- 按收款人分组统计
- 4工作表Excel输出
- Markdown格式消息

### ✅ 变更追踪
- 状态变更检测
- 金额变更检测
- 重要事件识别(大额/终止/逾期)
- 变更报告生成

### ✅ 钉钉推送
- 文本消息(汇总摘要)
- 文件消息(Excel附件)
- @用户提醒
- 群机器人接口

## 定时任务配置

### Linux/macOS (crontab)
```bash
# 每日同步(20:00)
0 20 * * * cd /path/to/dailyReport && python manage.py sync_payment_approvals

# 每周一发送周报(09:00)
0 9 * * 1 cd /path/to/dailyReport && python manage.py send_payment_report week --group-id <群ID>

# 每月1日发送月报(09:00)
0 9 1 * * cd /path/to/dailyReport && python manage.py send_payment_report month --group-id <群ID>
```

### Windows (任务计划程序)
```powershell
# 每日同步
schtasks /create /tn "SyncPaymentApprovals" `
  /tr "python E:\DEV\dailyReport\manage.py sync_payment_approvals" `
  /sc daily /st 20:00

# 每周一周报
schtasks /create /tn "PaymentWeeklyReport" `
  /tr "python E:\DEV\dailyReport\manage.py send_payment_report week --group-id <群ID>" `
  /sc weekly /d MON /st 09:00

# 每月1日月报
schtasks /create /tn "PaymentMonthlyReport" `
  /tr "python E:\DEV\dailyReport\manage.py send_payment_report month --group-id <群ID>" `
  /sc monthly /d 1 /st 09:00
```

## 常用命令

### 同步命令
```bash
# 基础同步(所有审批类型)
python manage.py sync_dingtalk

# 增强同步(仅付款申请,带变更追踪)
python manage.py sync_payment_approvals

# 指定公司
python manage.py sync_payment_approvals --company FNS

# 指定回看天数
python manage.py sync_payment_approvals --lookback-days 60

# 指定审批模板
python manage.py sync_payment_approvals \
  --process-code PROC-80780FFA-3A5F-436B-BC53-14CC357AAC0C

# Dry-run模式
python manage.py sync_payment_approvals --dry-run

# 强制重新同步
python manage.py sync_payment_approvals --force
```

### 报表命令
```bash
# 生成周报并发送
python manage.py send_payment_report week --group-id <群ID>

# 生成月报并发送
python manage.py send_payment_report month --group-id <群ID>

# 指定公司
python manage.py send_payment_report week --company FNS --group-id <群ID>

# 测试历史数据
python manage.py send_payment_report week \
  --base-date 2026-09-15 \
  --group-id <群ID>

# 仅生成不发送
python manage.py send_payment_report week \
  --output-dir ./reports \
  --dry-run

# @指定用户
python manage.py send_payment_report week \
  --group-id <群ID> \
  --mention user123 user456
```

## 获取钉钉群ID

### 方法1: 钉钉管理后台
1. 登录钉钉管理后台
2. 找到目标群 → 群设置
3. 查看 `openConversationId`

### 方法2: API查询
```python
# 在Django shell中
python manage.py shell

from integrations.models import DingtalkApp
from integrations.services.dingtalk_client import DingtalkClient

app = DingtalkApp.objects.get(company__code='FNS')
client = DingtalkClient(app)

# 调用群列表API(需相应权限)
# 具体API请参考钉钉开放平台文档
```

## 故障排查

### 问题1: 同步失败
```bash
# 检查钉钉应用配置
python manage.py shell
>>> from integrations.models import DingtalkApp
>>> DingtalkApp.objects.filter(is_active=True)

# 测试token获取
>>> from integrations.services.dingtalk_client import DingtalkClient
>>> app = DingtalkApp.objects.first()
>>> client = DingtalkClient(app)
>>> client.token()
```

### 问题2: 无数据
```bash
# 检查审批实例
python manage.py shell
>>> from integrations.models import DingtalkApprovalInstance
>>> DingtalkApprovalInstance.objects.filter(company__code='FNS').count()

# 检查时间范围
>>> from integrations.services.payment_report import get_last_week_range
>>> period = get_last_week_range()
>>> print(period)
```

### 问题3: 推送失败
```bash
# 验证群ID
# 确认机器人已加入群
# 检查应用权限(机器人消息发送)
```

## 架构说明

### 数据流
```
钉钉OA审批
    ↓
sync_payment_approvals (同步+变更追踪)
    ↓
DingtalkApprovalInstance (数据库)
    ↓
payment_report (汇总分析)
    ↓
payment_excel + payment_message (报表生成)
    ↓
send_payment_report (钉钉推送)
    ↓
钉钉群消息 + Excel附件
```

### 与原方案对比

| 维度 | 原方案 | 本实现 |
|-----|-------|-------|
| 技术栈 | Node.js + DWS CLI | Django + Python SDK |
| 数据源 | 实时API查询 | 数据库增量同步 |
| 配置 | config.json | Django Admin + 模型 |
| 部署 | 独立Node进程 | Django管理命令 |

## 扩展方向

### 短期(P1)
- [ ] 群配置模型化
- [ ] 发送记录表
- [ ] 失败重试机制
- [ ] 自定义消息模板

### 中期(P2)
- [ ] 图表可视化
- [ ] 多维度汇总(部门/项目)
- [ ] 趋势分析(同比/环比)
- [ ] 异常提醒

### 长期(P3)
- [ ] 机器人交互查询
- [ ] 与金蝶对账
- [ ] 应付/已付分析
- [ ] 预测模型

## 相关文档

- **详细使用指南**: `docs/payment_report_guide.md`
- **集成说明**: `docs/payment_report_integration.md`
- **技术总结**: `docs/payment_report_technical_summary.md`

## 技术支持

集成日期: 2026-10-26
开发团队: FNS数字化团队

如有问题:
1. 查看日志: `logs/integrations.log`
2. 提交Issue
3. 联系系统管理员
