# 钉钉付款申请功能 - 实施清单

## ✅ 已完成

### 代码集成
- [x] 4个核心服务模块
- [x] 2个Django管理命令
- [x] 2个测试脚本
- [x] 4个文档文件
- [x] 单元测试

### 功能验证
- [x] 依赖检查(openpyxl: 3.1.5, Django: 5.1.1)
- [x] 模块导入正常
- [x] 管理命令已注册
- [x] 时间范围计算正确(上周/上月)

## 📋 待配置

### 1. Django Admin配置

访问: `http://你的域名/admin/`

#### 配置钉钉应用 (integrations > 钉钉应用)
```
公司: [选择公司]
应用名称: 付款申请机器人
AppKey: [从钉钉开发者后台获取]
AppSecret: [从钉钉开发者后台获取]
CorpId: [企业ID]
AgentId: [机器人code/应用AgentId]
启用: ✓
```

#### 配置审批模板 (integrations > 钉钉审批模板)
```
钉钉应用: [选择刚创建的应用]
审批模板Code: PROC-80780FFA-3A5F-436B-BC53-14CC357AAC0C
模板名称: 付款申请
金额组件名: 付款总额
回看天数: 30
启用: ✓
```

**获取审批模板Code的方法**:
1. 登录钉钉管理后台
2. 工作台 → 审批 → 找到"付款申请"模板
3. 查看URL中的process_code参数

### 2. 同步审批数据

```bash
# 首次同步(回看30天)
python manage.py sync_payment_approvals --lookback-days 30

# 查看同步结果
python manage.py shell
>>> from integrations.models import DingtalkApprovalInstance
>>> DingtalkApprovalInstance.objects.count()
```

### 3. 测试报表生成

```bash
# Dry-run模式(仅生成Excel,不发送)
python manage.py send_payment_report week --dry-run --output-dir ./test_reports

# 检查生成的Excel
# 文件位于: ./test_reports/付款申请周报_XXX.xlsx
```

### 4. 获取钉钉群ID

**方法1: 钉钉管理后台**
1. 登录钉钉管理后台
2. 找到目标群 → 群设置
3. 查看openConversationId

**方法2: 联系钉钉管理员**
请管理员提供群的openConversationId

### 5. 测试发送

```bash
# 先在测试群测试(使用历史数据)
python manage.py send_payment_report week \
  --company FNS \
  --base-date 2026-09-15 \
  --group-id <测试群ID>

# 确认无误后,使用正式群ID
```

### 6. 配置定时任务

#### Windows任务计划程序

```powershell
# 每日同步(20:00)
schtasks /create /tn "SyncPaymentApprovals" `
  /tr "python E:\DEV\dailyReport\manage.py sync_payment_approvals" `
  /sc daily /st 20:00

# 每周一周报(09:00)
schtasks /create /tn "PaymentWeeklyReport" `
  /tr "python E:\DEV\dailyReport\manage.py send_payment_report week --company FNS --group-id <群ID>" `
  /sc weekly /d MON /st 09:00

# 每月1日月报(09:00)
schtasks /create /tn "PaymentMonthlyReport" `
  /tr "python E:\DEV\dailyReport\manage.py send_payment_report month --company FNS --group-id <群ID>" `
  /sc monthly /d 1 /st 09:00
```

**注意**: 将 `<群ID>` 替换为实际的openConversationId

## 🧪 验证步骤

### 1. 快速检查
```bash
python scripts/quick_check.py
```
预期输出:
```
[OK] openpyxl: 3.1.5
[OK] 模型导入成功
[OK] 服务模块导入成功
[OK] sync_payment_approvals 命令已注册
[OK] send_payment_report 命令已注册
```

### 2. 配置验证
```bash
python manage.py shell
>>> from integrations.models import DingtalkApp
>>> DingtalkApp.objects.filter(is_active=True)
>>> # 应该能看到配置的应用
```

### 3. 同步验证
```bash
python manage.py sync_payment_approvals --dry-run
# 应该显示找到N个审批实例
```

### 4. 报表验证
```bash
python manage.py send_payment_report week --dry-run --output-dir ./test
# 应该生成Excel文件,无报错
```

### 5. 推送验证
```bash
# 在测试群发送一次
python manage.py send_payment_report week --group-id <测试群ID>
# 检查群消息和Excel附件
```

## 📊 预期效果

### Excel报表包含:
- **工作表1**: 汇总统计(周期/总数/总金额/按状态分类)
- **工作表2**: 按收款人汇总(收款人/申请数/金额/状态分布)
- **工作表3**: 详细清单(逐条审批明细)
- **工作表4**: 原始JSON数据

### 钉钉消息包含:
- 统计摘要(总计/已完成/进行中)
- 按收款人分组(前10个)
- 每个收款人的前5条明细
- Excel报表下载链接
- @用户提醒

## ❗ 常见问题

### Q1: 命令找不到
```bash
# 确认命令已注册
python manage.py help | grep payment

# 应该看到:
#   send_payment_report
#   sync_payment_approvals
```

### Q2: 没有审批数据
```bash
# 检查配置
python manage.py shell
>>> from integrations.models import DingtalkProcessConfig
>>> DingtalkProcessConfig.objects.filter(is_active=True)

# 手动同步
python manage.py sync_payment_approvals --force
```

### Q3: 钉钉推送失败
```bash
# 测试token获取
python manage.py shell
>>> from integrations.models import DingtalkApp
>>> from integrations.services.dingtalk_client import DingtalkClient
>>> app = DingtalkApp.objects.first()
>>> client = DingtalkClient(app)
>>> token = client.token()
>>> print(token)  # 应该返回一个token字符串
```

### Q4: Excel样式异常
```bash
# 确认openpyxl版本
pip show openpyxl
# 应该是 3.1.5 或更高
```

## 📂 文件清单

### 核心代码(8个文件)
```
integrations/
├── services/
│   ├── payment_report.py           # 数据汇总
│   ├── payment_excel.py            # Excel生成
│   ├── payment_message.py          # 消息构建
│   └── payment_changes.py          # 变更追踪
└── management/commands/
    ├── sync_payment_approvals.py   # 同步命令
    └── send_payment_report.py      # 发送命令

integrations/tests/
└── test_payment_report.py          # 单元测试

scripts/
├── test_payment_report.py          # 完整测试(交互式)
└── quick_check.py                  # 快速检查(非交互)
```

### 文档(4个文件)
```
docs/
├── README_payment_report.md                # 快速入门 ⭐
├── payment_report_guide.md                 # 详细指南
├── payment_report_integration.md           # 集成说明
├── payment_report_technical_summary.md     # 技术总结
└── payment_report_checklist.md             # 本文件
```

## 🎯 实施进度追踪

- [ ] 1. Django Admin配置钉钉应用
- [ ] 2. Django Admin配置审批模板
- [ ] 3. 运行首次同步
- [ ] 4. 验证审批数据
- [ ] 5. 生成测试报表(dry-run)
- [ ] 6. 获取钉钉群ID
- [ ] 7. 测试发送到测试群
- [ ] 8. 配置定时任务(同步)
- [ ] 9. 配置定时任务(周报)
- [ ] 10. 配置定时任务(月报)
- [ ] 11. 监控首次正式发送
- [ ] 12. 文档交接

## 📞 技术支持

- 日志文件: `logs/integrations.log`
- 快速检查: `python scripts/quick_check.py`
- 详细文档: `docs/README_payment_report.md`

---

**实施完成日期**: 2026-10-26
**开发团队**: FNS数字化团队
**技术栈**: Django 5.1 + Python 3.13 + openpyxl 3.1.5
