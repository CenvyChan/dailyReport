# 钉钉付款申请周报/月报功能说明

## 功能概述

自动汇总钉钉OA审批中的付款申请数据,生成Excel报表并推送到钉钉群:
- **周报**: 每周一早上9点汇总上周(周一至周日)的付款申请
- **月报**: 每月1日早上9点汇总上月(1号至月末)的付款申请
- **按收款人分组**: 统计每个收款人的申请数和总金额
- **双重输出**: 钉钉卡片消息 + Excel报表文件

## 实现方式

### 架构说明

与原方案(Node.js + DWS CLI)不同,本实现**完全基于Django和现有Python基础设施**:

1. **数据来源**: 读取已通过 `sync_dingtalk` 命令同步到本地数据库的 `DingtalkApprovalInstance` 记录
2. **报表生成**: 使用 `openpyxl` 生成4个工作表的Excel文件
3. **钉钉推送**: 复用现有 `DingtalkClient` 的token/upload/post能力

### 核心文件

```
integrations/
├── services/
│   ├── payment_report.py       # 数据汇总逻辑
│   ├── payment_excel.py        # Excel报表生成
│   └── payment_message.py      # 钉钉消息构建
└── management/commands/
    └── send_payment_report.py  # Django管理命令
```

## 前置条件

### 1. 安装依赖

```bash
pip install openpyxl
```

### 2. 配置钉钉应用

确保已在Django Admin中配置:

**钉钉应用** (`integrations.DingtalkApp`)
- 公司
- AppKey/AppSecret(加密存储)
- CorpId
- AgentId(机器人code)

**审批模板** (`integrations.DingtalkProcessConfig`)
- 审批模板Code(如 `PROC-80780FFA-3A5F-436B-BC53-14CC357AAC0C`)
- 模板名称(如"付款申请")
- 金额组件名(如"付款总额")

### 3. 同步审批数据

周报/月报依赖已同步的审批实例数据,需先运行同步命令:

```bash
# 每日同步(建议定时任务在20:00执行)
python manage.py sync_dingtalk

# 手动同步指定公司
python manage.py sync_dingtalk --company FNS

# 同步历史数据
python manage.py sync_dingtalk --date 2026-10-20 --force
```

## 使用方法

### 命令行用法

```bash
# 生成并发送周报
python manage.py send_payment_report week --group-id <群ID>

# 生成并发送月报
python manage.py send_payment_report month --group-id <群ID>

# 指定公司
python manage.py send_payment_report week --company FNS --group-id <群ID>

# 指定审批模板
python manage.py send_payment_report week \
  --process-code PROC-80780FFA-3A5F-436B-BC53-14CC357AAC0C \
  --group-id <群ID>

# 测试历史数据(生成上周/上月数据)
python manage.py send_payment_report week \
  --base-date 2026-10-20 \
  --group-id <群ID>

# Dry-run模式(仅生成Excel,不发送)
python manage.py send_payment_report week \
  --output-dir ./reports \
  --dry-run

# @指定用户
python manage.py send_payment_report week \
  --group-id <群ID> \
  --mention user123 user456
```

### 参数说明

| 参数 | 说明 | 示例 |
|-----|------|------|
| `report_type` | 报表类型(必填) | `week` 或 `month` |
| `--company` | 公司代码 | `FNS` |
| `--group-id` | 钉钉群ID(必填) | `cid6vVsD8T97` |
| `--process-code` | 审批模板Code | `PROC-8078...` |
| `--base-date` | 基准日期(测试用) | `2026-10-20` |
| `--output-dir` | Excel输出目录 | `./reports` |
| `--dry-run` | 仅生成不发送 | - |
| `--mention` | @用户ID列表 | `user123 user456` |

## 获取钉钉群ID

由于项目暂未集成DWS CLI,需通过以下方式获取群ID:

### 方式1: 钉钉开放平台API

```python
# 在Django shell中执行
from integrations.models import DingtalkApp
from integrations.services.dingtalk_client import DingtalkClient

app = DingtalkApp.objects.get(company__code='FNS')
client = DingtalkClient(app)

# 调用API获取群列表(需要相应权限)
# 具体API请参考钉钉开放平台文档
```

### 方式2: 钉钉管理后台

1. 登录钉钉管理后台
2. 找到目标群聊
3. 在群设置中查看群ID(openConversationId)

### 方式3: 通过机器人消息事件

配置机器人消息接收回调,从回调事件中获取conversationId。

## 定时任务配置

### Linux/macOS (crontab)

```bash
# 编辑定时任务
crontab -e

# 每周一早上9点发送周报
0 9 * * 1 cd /path/to/dailyReport && python manage.py send_payment_report week --group-id <群ID> >> /var/log/payment_report.log 2>&1

# 每月1号早上9点发送月报
0 9 1 * * cd /path/to/dailyReport && python manage.py send_payment_report month --group-id <群ID> >> /var/log/payment_report.log 2>&1
```

### Windows (任务计划程序)

```powershell
# 周报任务
schtasks /create /tn "PaymentWeeklyReport" `
  /tr "python E:\DEV\dailyReport\manage.py send_payment_report week --group-id <群ID>" `
  /sc weekly /d MON /st 09:00 /ru SYSTEM

# 月报任务
schtasks /create /tn "PaymentMonthlyReport" `
  /tr "python E:\DEV\dailyReport\manage.py send_payment_report month --group-id <群ID>" `
  /sc monthly /d 1 /st 09:00 /ru SYSTEM
```

### Docker/K8s (CronJob)

参考项目现有的定时任务配置方式(如日报发送)。

## Excel报表结构

生成的Excel包含4个工作表:

### 1. 汇总统计
- 统计周期
- 起止日期
- 总申请数/总金额
- 按状态分类统计

### 2. 按收款人汇总
- 收款人
- 申请数
- 总金额
- 已完成/进行中/已终止数量

### 3. 详细清单
- 申请日期
- 收款人
- 付款金额
- 付款事由
- 期望付款日期
- 状态
- 申请人
- 审批标题
- 审批实例ID

### 4. 原始JSON数据
- 完整的结构化数据(JSON格式)
- 便于二次分析和处理

## 钉钉消息格式

发送到群的消息为**简洁版Markdown格式**,适合移动端阅读:

```
📊 付款申请周报
━━━━━━━━━━━━━━━━━━
📅 2026-10-20 至 2026-10-26

📈 总计:5条 | ¥256,000.00
✅ 已完成:3条 | 🔄 进行中:2条

━━━━━━━━━━━━━━━━━━
💰 收款人汇总
━━━━━━━━━━━━━━━━━━

1️⃣ 宁波金睿信息技术有限公司
   3条 | ¥180,000.00

   • 10-21 | ¥100,000.00 | ✅已完成
     金蝶云项目验收阶段尾款
   
   • 10-22 | ¥50,000.00 | 🔄进行中
     软件服务费第二期款
   
   ...还有1条申请,详见Excel报表

━━━━━━━━━━━━━━━━━━
📎 Excel报表已生成
   详细数据请查看附件

💬 @user123 请查收本周付款汇总
```

## 数据提取逻辑

从审批表单中提取字段时,会按优先级尝试多个可能的字段名:

- **收款人**: `收款人全称` > `收款人` > `收款方` > `收款单位` > `供应商`
- **付款事由**: `付款事由` > `事由` > `用途` > `备注`
- **期望日期**: `期望付款日期` > `期望日期` > `计划付款日期`

这样可以兼容不同企业的审批模板字段命名。

## 注意事项

### 1. 审批实例同步

- 报表数据来源于本地数据库,必须先运行 `sync_dingtalk` 同步
- 建议每晚定时同步,确保数据完整性
- 周报/月报发送前,会查询对应时间范围的已同步数据

### 2. 钉钉机器人配置

当前实现使用钉钉企业内部应用的**机器人消息接口**,需要:
- 在钉钉开发者后台创建企业内部应用
- 开通"机器人消息发送"权限
- 配置 `AgentId`(即机器人code)
- 将机器人添加到目标群聊

### 3. 群ID获取

由于暂未集成完整的群管理功能,首次使用需手动获取并配置群ID。
后续可扩展 `DingtalkGroupConfig` 模型来管理多个推送目标。

### 4. 数据安全

- 付款金额等敏感信息仅在授权群内推送
- Excel文件通过钉钉媒体上传,有访问权限控制
- 审批实例ID可用于追溯和审计

## 扩展方向

### 短期优化
1. 扩展 `DingtalkGroupConfig` 模型,支持多群推送配置
2. 添加 `--no-excel` 选项,仅发送文本摘要
3. 支持自定义消息模板
4. 添加发送失败重试机制

### 长期规划
1. 集成钉钉群管理API,自动发现可推送的群
2. 支持按部门/项目维度汇总
3. 对接付款流水,实现应付/已付对比
4. 图表可视化(生成图片推送)

## 故障排查

### 问题1: 找不到审批数据

**症状**: 报表显示"0条付款申请"

**排查步骤**:
```bash
# 1. 检查审批实例是否已同步
python manage.py shell
>>> from integrations.models import DingtalkApprovalInstance
>>> DingtalkApprovalInstance.objects.filter(company__code='FNS').count()

# 2. 检查时间范围
>>> from integrations.services.payment_report import get_last_week_range
>>> period = get_last_week_range()
>>> print(period)

# 3. 检查审批模板Code
>>> from integrations.models import DingtalkProcessConfig
>>> DingtalkProcessConfig.objects.filter(app__company__code='FNS')
```

### 问题2: 发送失败

**症状**: "钉钉接口失败"错误

**排查步骤**:
1. 检查 `DingtalkApp` 配置(AppKey/AppSecret/AgentId)
2. 验证群ID是否正确
3. 确认机器人已加入目标群
4. 检查应用权限(机器人消息发送)

### 问题3: Excel生成失败

**症状**: "未安装 openpyxl"错误

**解决方法**:
```bash
pip install openpyxl
```

## 测试建议

### 1. 单元测试

```bash
# 测试数据汇总
python manage.py shell
>>> from integrations.services.payment_report import analyze_payment_applications
>>> # 测试代码...

# 测试Excel生成
>>> from integrations.services.payment_excel import generate_payment_excel
>>> # 测试代码...
```

### 2. 集成测试

```bash
# Dry-run模式测试完整流程
python manage.py send_payment_report week \
  --company FNS \
  --output-dir ./test_reports \
  --dry-run

# 检查生成的Excel文件
ls -lh ./test_reports/
```

### 3. 真实环境测试

```bash
# 先测试历史数据(不会影响生产)
python manage.py send_payment_report week \
  --base-date 2026-09-01 \
  --group-id <测试群ID>

# 确认无误后,配置定时任务
```

## 相关文档

- [钉钉开放平台文档](https://open.dingtalk.com/)
- [机器人群消息API](https://open.dingtalk.com/document/orgapp/robot-overview)
- [审批接口文档](https://open.dingtalk.com/document/orgapp/approval-overview)
- 项目内相关代码:
  - `integrations/services/dingtalk_client.py`
  - `integrations/management/commands/sync_dingtalk.py`
  - `notifications/management/commands/send_daily_report.py`

## 联系支持

如有问题,请:
1. 查看日志: `logs/integrations.log`
2. 提交Issue并附上错误信息
3. 联系系统管理员
