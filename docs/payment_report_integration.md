# 钉钉付款申请周报/月报功能集成说明

## 概述

本次集成为 `dailyReport` 项目新增了**钉钉付款申请自动汇总与推送**功能,完全基于现有Django架构实现。

## 新增文件清单

```
integrations/
├── services/
│   ├── payment_report.py           # 数据汇总与分析(核心逻辑)
│   ├── payment_excel.py            # Excel报表生成
│   └── payment_message.py          # 钉钉消息构建
└── management/commands/
    └── send_payment_report.py      # Django管理命令

docs/
└── payment_report_guide.md         # 详细使用文档

scripts/
└── test_payment_report.py          # 快速测试脚本
```

## 与原方案的主要差异

| 维度 | 原方案(Node.js) | 本实现(Django) |
|-----|----------------|---------------|
| **技术栈** | Node.js + DWS CLI | Python + Django ORM |
| **数据来源** | 实时调用钉钉API | 读取已同步的数据库记录 |
| **部署方式** | 独立Node进程 | Django管理命令 |
| **配置管理** | config.json | Django Admin + 模型 |
| **依赖项** | exceljs + dws | openpyxl(已在项目中) |

### 架构优势

1. **复用现有基础设施**:
   - `DingtalkClient`: token管理、文件上传、API调用
   - `DingtalkApprovalInstance`: 审批数据已持久化
   - 加密密钥管理、日志系统、配置模型全部共享

2. **数据一致性**:
   - 报表数据与日报系统使用同一数据源
   - 避免实时API查询的不确定性
   - 支持历史数据回溯和测试

3. **运维简化**:
   - 单一技术栈,无需Node环境
   - 定时任务与现有日报发送共用调度机制
   - 日志统一在Django logging框架下

## 核心实现要点

### 1. 数据汇总 (`payment_report.py`)

**时间范围计算**:
```python
# 上周: 上周一00:00 到上周日23:59
period = get_last_week_range()

# 上月: 上月1号00:00 到月末23:59
period = get_last_month_range()
```

**按收款人分组**:
- 从 `DingtalkApprovalInstance.form_values` JSON字段提取收款人
- 支持多种字段名(收款人全称/收款人/收款方...)
- 按金额倒序排列

**状态统计**:
- COMPLETED(已完成)
- RUNNING(进行中)
- TERMINATED(已终止)
- NEW(新建)

### 2. Excel生成 (`payment_excel.py`)

使用 `openpyxl` 生成4个工作表:
1. **汇总统计**: 总览数据
2. **按收款人汇总**: 分组统计
3. **详细清单**: 逐条审批明细
4. **原始JSON**: 完整结构化数据

**样式设置**:
- 表头灰色背景、加粗
- 金额千分位格式
- 自动列宽

### 3. 消息构建 (`payment_message.py`)

**简洁Markdown格式**:
- Emoji状态指示(✅🔄❌)
- 移动端友好(避免过长文本)
- 智能截断(收款人最多10个,明细最多5条)
- 支持@用户提醒

### 4. 管理命令 (`send_payment_report.py`)

**功能特性**:
- 支持周报/月报切换
- 支持单公司或全部公司
- Dry-run模式(仅生成不发送)
- 历史数据测试(--base-date)
- 多用户@提醒

**钉钉推送流程**:
1. 上传Excel到钉钉媒体库(获取media_id)
2. 发送文本消息(包含汇总信息)
3. 发送文件消息(Excel下载)

## 快速开始

### 1. 安装依赖

依赖 `openpyxl` 已在 `requirements.txt` 中:
```bash
pip install -r requirements.txt
```

### 2. 配置钉钉

在 Django Admin 中配置:
- **钉钉应用**: AppKey/AppSecret/CorpId/AgentId
- **审批模板**: 付款申请的 process_code

### 3. 同步审批数据

```bash
# 首次同步
python manage.py sync_dingtalk --company FNS

# 定时同步(建议每晚20:00)
python manage.py sync_dingtalk
```

### 4. 测试报表

```bash
# 交互式测试
python scripts/test_payment_report.py

# 手动命令测试
python manage.py send_payment_report week --output-dir ./reports --dry-run
```

### 5. 配置定时任务

#### Linux/macOS (crontab)
```bash
# 每周一9点发送周报
0 9 * * 1 cd /path/to/dailyReport && python manage.py send_payment_report week --group-id <群ID>

# 每月1号9点发送月报
0 9 1 * * cd /path/to/dailyReport && python manage.py send_payment_report month --group-id <群ID>
```

#### Windows (任务计划程序)
```powershell
schtasks /create /tn "PaymentWeeklyReport" `
  /tr "python E:\DEV\dailyReport\manage.py send_payment_report week --group-id <群ID>" `
  /sc weekly /d MON /st 09:00
```

## 获取钉钉群ID

### 方法1: 钉钉管理后台
1. 登录钉钉管理后台
2. 找到目标群 → 群设置
3. 查看 `openConversationId`

### 方法2: API查询(需开发)
```python
# 在Django shell中
from integrations.services.dingtalk_client import DingtalkClient
client = DingtalkClient(app)
# 调用群列表API(需相应权限)
```

### 方法3: 机器人回调
配置机器人消息接收,从回调事件获取conversationId。

## 命令行参考

```bash
# 基本用法
python manage.py send_payment_report {week|month} --group-id <群ID>

# 指定公司
python manage.py send_payment_report week --company FNS --group-id <群ID>

# 指定审批模板
python manage.py send_payment_report week \
  --process-code PROC-80780FFA-3A5F-436B-BC53-14CC357AAC0C \
  --group-id <群ID>

# 测试历史数据
python manage.py send_payment_report week \
  --base-date 2026-09-15 \
  --group-id <群ID>

# Dry-run模式
python manage.py send_payment_report week \
  --output-dir ./test_reports \
  --dry-run

# @指定用户
python manage.py send_payment_report week \
  --group-id <群ID> \
  --mention user123 user456
```

## 与现有功能的集成点

### 1. 数据模型层
- **复用**: `DingtalkApp`, `DingtalkProcessConfig`, `DingtalkApprovalInstance`
- **扩展**: 未来可添加 `PaymentReportConfig` 模型管理多群推送

### 2. 服务层
- **复用**: `DingtalkClient` (token/upload/post)
- **新增**: `payment_*` 系列服务模块

### 3. 管理命令层
- **参考**: `sync_dingtalk` 的命令结构和参数设计
- **对齐**: `send_daily_report` 的推送逻辑

### 4. 定时任务层
- **共享**: 同一调度机制(cron/schtasks)
- **隔离**: 独立命令,互不干扰

## 扩展建议

### 短期优化(P1)
1. **群配置模型化**:
   ```python
   class PaymentReportConfig(models.Model):
       company = ForeignKey(Company)
       group_id = CharField()
       mention_users = JSONField()
       enable_weekly = BooleanField(default=True)
       enable_monthly = BooleanField(default=True)
   ```

2. **发送记录追踪**:
   - 参考 `ReportDelivery` 模型
   - 记录发送时间、状态、错误信息
   - 支持失败重试

3. **自定义消息模板**:
   - 支持模板变量替换
   - 企业定制化消息格式

### 中期功能(P2)
1. **图表可视化**:
   - 使用 `matplotlib` 生成柱状图/饼图
   - 嵌入消息或作为图片附件

2. **多维度汇总**:
   - 按部门分组
   - 按项目/成本中心分组
   - 按审批人分组

3. **趋势分析**:
   - 与上周/上月对比
   - 同比/环比增长率

### 长期规划(P3)
1. **智能提醒**:
   - 异常金额预警
   - 逾期付款提醒
   - 审批进度跟踪

2. **数据对接**:
   - 与金蝶付款单对账
   - 应付/已付差异分析

3. **自助查询**:
   - 钉钉群内机器人交互
   - 自定义日期范围查询
   - 按收款人筛选

## 测试建议

### 单元测试
```python
# 测试汇总逻辑
from integrations.services.payment_report import analyze_payment_applications
# ...

# 测试Excel生成
from integrations.services.payment_excel import generate_payment_excel
# ...
```

### 集成测试
```bash
# 完整流程测试
python scripts/test_payment_report.py

# 验证Excel内容
python -c "
import openpyxl
wb = openpyxl.load_workbook('test_reports/xxx.xlsx')
print(wb.sheetnames)
"
```

### 生产验证
1. 先在测试群发送历史数据
2. 验证Excel内容准确性
3. 确认消息格式正确
4. 配置正式群和定时任务

## 故障排查

### 问题: 无审批数据
**原因**: 未同步或时间范围不匹配
**解决**: 
```bash
python manage.py sync_dingtalk --force
python manage.py shell
>>> from integrations.models import DingtalkApprovalInstance
>>> DingtalkApprovalInstance.objects.all().count()
```

### 问题: 钉钉推送失败
**原因**: 配置错误或权限不足
**检查**:
1. `AgentId` 是否正确(机器人code)
2. 机器人是否已加入群
3. 应用是否有"机器人消息发送"权限

### 问题: Excel样式异常
**原因**: openpyxl版本不兼容
**解决**: 
```bash
pip install --upgrade openpyxl
```

## 相关文档

- 详细使用指南: `docs/payment_report_guide.md`
- 快速测试脚本: `scripts/test_payment_report.py`
- 钉钉API文档: https://open.dingtalk.com/
- 现有同步命令: `integrations/management/commands/sync_dingtalk.py`

## 维护者

集成完成日期: 2026-10-26
基于原方案: `C:\Users\FNS_CenvyChan\.claude\plans\eager-wishing-penguin.md`
技术栈调整: Node.js + DWS CLI → Django + Python SDK

如有问题请提交Issue或联系开发团队。
