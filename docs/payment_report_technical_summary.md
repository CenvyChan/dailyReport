# 钉钉付款申请完整功能集成 - 技术总结

## 功能全景

本次集成为 `dailyReport` 项目构建了**完整的钉钉付款申请管理体系**,包含:

### 1. 数据同步层
- **基础同步**: 复用现有 `sync_dingtalk` 命令
- **增强同步**: 新增 `sync_payment_approvals` 命令
  - ✅ 增量更新(按lookback_days回看)
  - ✅ 状态变更追踪(RUNNING→COMPLETED等)
  - ✅ 金额校正追踪(审批修改监控)
  - ✅ 幂等性(支持多次运行)
  - ✅ Dry-run模式

### 2. 报表生成层
- **数据汇总**: `payment_report.py`
  - 按周/月时间范围过滤
  - 按收款人分组统计
  - 多维度状态分析
- **Excel输出**: `payment_excel.py`
  - 4工作表结构(汇总/分组/明细/原始)
  - 样式美化(表头、格式、对齐)
  - 金额千分位格式
- **消息构建**: `payment_message.py`
  - 移动端友好的Markdown
  - 智能截断(避免过长)
  - Emoji状态指示

### 3. 变更追踪层
- **变更检测**: `payment_changes.py`
  - 状态变更(→COMPLETED/TERMINATED)
  - 金额变更(差额计算)
  - 新增大额申请
- **重要事件识别**:
  - 大额变更(>10000元)
  - 审批终止事件
  - 新增大额申请(>50000元)
  - 逾期未完成(>7天)
- **变更报告**:
  - 按公司分组
  - 按类型统计
  - 重要变更列表

### 4. 推送发送层
- **命令接口**: `send_payment_report.py`
  - 支持周报/月报
  - 支持单/多公司
  - 支持@用户提醒
  - Dry-run测试模式
- **钉钉推送**:
  - 文本消息(汇总摘要)
  - 文件消息(Excel附件)
  - 群机器人接口

## 技术架构

```
┌─────────────────────────────────────────────┐
│          钉钉开放平台 API                     │
│  (审批接口 / 群消息接口 / 媒体上传接口)         │
└──────────────┬──────────────────────────────┘
               │
               ↓
┌─────────────────────────────────────────────┐
│      同步层 (Sync Layer)                      │
│  ┌─────────────────────────────────────┐    │
│  │ sync_dingtalk (基础同步)              │    │
│  │ - 所有审批类型的通用同步               │    │
│  │ - 按process_code过滤                 │    │
│  └─────────────────────────────────────┘    │
│  ┌─────────────────────────────────────┐    │
│  │ sync_payment_approvals (增强同步)     │    │
│  │ - 专注付款申请                         │    │
│  │ - 增量更新 + 变更追踪                  │    │
│  │ - 状态/金额变化监控                    │    │
│  └─────────────────────────────────────┘    │
└──────────────┬──────────────────────────────┘
               │
               ↓
┌─────────────────────────────────────────────┐
│    数据层 (Data Layer)                        │
│  DingtalkApprovalInstance (审批实例表)        │
│  - process_instance_id (唯一键)              │
│  - status (状态)                             │
│  - amount (金额)                             │
│  - form_values (表单JSON)                    │
│  - created_at / updated_at                   │
└──────────────┬──────────────────────────────┘
               │
               ↓
┌─────────────────────────────────────────────┐
│    服务层 (Service Layer)                     │
│  ┌─────────────────────────────────────┐    │
│  │ payment_report                       │    │
│  │ - 时间范围计算                        │    │
│  │ - 按收款人汇总                        │    │
│  │ - 状态统计                            │    │
│  └─────────────────────────────────────┘    │
│  ┌─────────────────────────────────────┐    │
│  │ payment_changes                      │    │
│  │ - 变更检测                            │    │
│  │ - 重要事件识别                        │    │
│  │ - 变更报告生成                        │    │
│  └─────────────────────────────────────┘    │
│  ┌─────────────────────────────────────┐    │
│  │ payment_excel                        │    │
│  │ - 4工作表生成                         │    │
│  │ - 样式格式化                          │    │
│  └─────────────────────────────────────┘    │
│  ┌─────────────────────────────────────┐    │
│  │ payment_message                      │    │
│  │ - Markdown构建                       │    │
│  │ - 智能截断                            │    │
│  └─────────────────────────────────────┘    │
└──────────────┬──────────────────────────────┘
               │
               ↓
┌─────────────────────────────────────────────┐
│    命令层 (Command Layer)                     │
│  send_payment_report                         │
│  - 周报/月报调度                              │
│  - 公司维度处理                               │
│  - 钉钉群推送                                 │
│  - 错误处理 & 重试                            │
└─────────────────────────────────────────────┘
```

## 数据流

### 流程1: 每日同步(建议20:00执行)
```
1. 定时任务触发
   ↓
2. sync_payment_approvals
   ↓
3. 调用钉钉API获取审批列表(最近N天)
   ↓
4. 逐条获取审批详情
   ↓
5. 对比本地记录:
   - 新增 → 插入
   - 状态变化 → 更新 + 记录变更
   - 金额变化 → 更新 + 记录变更
   ↓
6. 生成变更摘要日志
   ↓
7. (可选)发送变更通知到钉钉
```

### 流程2: 周报发送(每周一09:00)
```
1. 定时任务触发
   ↓
2. send_payment_report week
   ↓
3. 计算上周范围(上周一~上周日)
   ↓
4. 从数据库查询已同步的审批实例
   ↓
5. payment_report.analyze_payment_applications
   - 按收款人分组
   - 统计金额/数量
   - 按状态分类
   ↓
6. payment_excel.generate_payment_excel
   - 生成4个工作表
   - 应用样式格式
   ↓
7. payment_message.build_payment_report_message
   - 构建Markdown消息
   - 添加@提醒
   ↓
8. DingtalkClient推送
   - 上传Excel获取media_id
   - 发送文本消息
   - 发送文件消息
   ↓
9. 记录发送结果
```

### 流程3: 月报发送(每月1日09:00)
```
与周报类似,时间范围改为上月1号~上月末
```

## 关键设计决策

### 决策1: 为何不用DWS CLI?

**原方案**: Node.js + DWS CLI(钉钉工作台CLI工具)

**调整为**: Django + Python SDK

**原因**:
1. **技术栈统一**: 避免Node.js额外依赖,简化部署
2. **数据一致性**: 复用已同步的数据库记录,避免实时API不确定性
3. **基础设施共享**: token管理/加密/日志全部复用
4. **测试友好**: Django ORM便于构造测试数据

### 决策2: 双命令体系

**基础同步** (`sync_dingtalk`):
- 通用审批同步命令
- 支持所有审批类型(付款申请/请假/报销...)
- 已在生产环境运行

**增强同步** (`sync_payment_approvals`):
- 专注付款申请
- 增量更新 + 变更追踪
- 更丰富的统计信息

**为何不合并**?
- 职责分离:通用 vs 专用
- 兼容性:不影响现有调度
- 灵活性:付款申请可单独调度

### 决策3: 数据持久化 vs 实时查询

**选择**: 数据持久化(先同步,后查询)

**优势**:
- ✅ 性能:避免实时API延迟
- ✅ 稳定:不受钉钉API限流影响
- ✅ 可测:支持历史数据回溯
- ✅ 可审:变更历史可追溯

**劣势**:
- ❌ 延迟:数据不是实时最新(可接受,同步频率1天)
- ❌ 存储:需要数据库空间(可接受,数据量不大)

### 决策4: 4工作表Excel结构

**设计**:
1. 汇总统计(高层概览)
2. 按收款人汇总(中层分组)
3. 详细清单(细节明细)
4. 原始JSON(原始数据)

**原因**:
- 满足不同角色需求(管理层/财务/审计)
- 支持二次分析(Excel透视表/Power BI)
- 可追溯(保留原始数据)

## 扩展路径

### 阶段1: 基础功能(已完成 ✅)
- [x] 数据同步
- [x] 周报/月报生成
- [x] Excel输出
- [x] 钉钉推送
- [x] 变更追踪

### 阶段2: 功能增强(短期)
- [ ] 群配置模型化(`PaymentReportConfig`)
- [ ] 发送记录表(`PaymentReportDelivery`)
- [ ] 失败重试机制
- [ ] 自定义消息模板
- [ ] 变更通知(每日同步后推送变更摘要)

### 阶段3: 数据分析(中期)
- [ ] 趋势图表(matplotlib/echarts)
- [ ] 同比/环比分析
- [ ] 多维度汇总(部门/项目/成本中心)
- [ ] 逾期提醒(超7天未完成自动@)
- [ ] 异常预警(大额/频繁修改)

### 阶段4: 智能化(长期)
- [ ] 机器人交互(群内@机器人查询)
- [ ] 自定义日期范围查询
- [ ] 按收款人筛选
- [ ] 与金蝶付款单对账
- [ ] 应付/已付差异分析
- [ ] 预测模型(基于历史数据)

## 运维指南

### 日常运维

**1. 监控同步状态**
```bash
# 查看最近同步记录
python manage.py shell
>>> from integrations.models import SyncRun
>>> SyncRun.objects.filter(integration='DINGTALK').order_by('-started_at')[:10]
```

**2. 检查数据质量**
```bash
# 统计审批数量
>>> from integrations.models import DingtalkApprovalInstance
>>> DingtalkApprovalInstance.objects.filter(
...     company__code='FNS',
...     process_code='PROC-XXX'
... ).count()

# 检查金额为空的记录
>>> DingtalkApprovalInstance.objects.filter(amount__isnull=True).count()
```

**3. 测试报表生成**
```bash
# Dry-run测试
python manage.py send_payment_report week --dry-run --output-dir ./test

# 历史数据测试
python manage.py send_payment_report week \
  --base-date 2026-09-15 \
  --dry-run
```

**4. 查看变更日志**
```bash
# 查看同步日志
tail -f logs/integrations.log | grep payment

# 查看变更记录
python manage.py shell
>>> from integrations.services.payment_changes import generate_change_summary
>>> summary = generate_change_summary(company, start_date, end_date)
>>> print(summary)
```

### 故障处理

**场景1: 同步失败**
```bash
# 症状: sync_payment_approvals 报错

# 排查步骤:
1. 检查钉钉应用配置(AppKey/AppSecret/AgentId)
2. 检查网络连接(能否访问 oapi.dingtalk.com)
3. 检查审批模板配置(process_code是否正确)
4. 查看详细错误日志

# 解决:
python manage.py sync_payment_approvals \
  --company FNS \
  --lookback-days 1 \
  --force
```

**场景2: 报表数据为空**
```bash
# 症状: 周报显示"0条付款申请"

# 排查步骤:
1. 确认数据已同步
   >>> DingtalkApprovalInstance.objects.filter(company__code='FNS').count()

2. 确认时间范围
   >>> from integrations.services.payment_report import get_last_week_range
   >>> period = get_last_week_range()
   >>> print(period)

3. 确认审批模板匹配
   >>> DingtalkApprovalInstance.objects.filter(
   ...     company__code='FNS',
   ...     process_code='PROC-XXX'
   ... ).count()

# 解决:
# 重新同步历史数据
python manage.py sync_payment_approvals \
  --company FNS \
  --lookback-days 30 \
  --force
```

**场景3: 钉钉推送失败**
```bash
# 症状: "钉钉接口失败"错误

# 排查步骤:
1. 验证群ID是否正确
2. 确认机器人已加入群
3. 检查应用权限(机器人消息发送)
4. 测试token获取

# 测试:
python manage.py shell
>>> from integrations.models import DingtalkApp
>>> from integrations.services.dingtalk_client import DingtalkClient
>>> app = DingtalkApp.objects.get(company__code='FNS')
>>> client = DingtalkClient(app)
>>> token = client.token()
>>> print(token)
```

### 性能优化

**1. 批量查询优化**
```python
# 使用 select_related 减少数据库查询
queryset = DingtalkApprovalInstance.objects.filter(
    company=company
).select_related('company')
```

**2. 分页处理大数据集**
```python
# 处理大量审批实例时,使用iterator()
for instance in queryset.iterator(chunk_size=100):
    # 处理逻辑
    pass
```

**3. 缓存token**
```python
# DingtalkClient 已实现token缓存
# token有效期7200秒,自动续期
```

## 测试策略

### 单元测试
```bash
# 运行付款申请相关测试
python manage.py test integrations.tests.test_payment_report

# 测试覆盖:
# - 时间范围计算
# - 数据汇总逻辑
# - 空数据处理
# - 字段提取兼容性
```

### 集成测试
```bash
# 使用测试脚本
python scripts/test_payment_report.py

# 测试流程:
# 1. 检查依赖
# 2. 检查配置
# 3. 检查数据
# 4. 生成测试报表
```

### 生产验证
```bash
# 1. 先在测试群验证
python manage.py send_payment_report week \
  --company FNS \
  --group-id <测试群ID> \
  --base-date 2026-09-15

# 2. 验证Excel内容
# 3. 验证消息格式
# 4. 配置正式群和定时任务
```

## 相关文档索引

- **使用指南**: `docs/payment_report_guide.md`
- **集成说明**: `docs/payment_report_integration.md`
- **测试脚本**: `scripts/test_payment_report.py`
- **原方案参考**: `C:\Users\FNS_CenvyChan\.claude\plans\eager-wishing-penguin.md`

## 贡献者

集成完成日期: 2026-10-26
开发团队: FNS数字化团队
技术栈: Django 5.1 + Python 3.x + openpyxl + 钉钉开放平台API

---

**下一步行动**:
1. 配置钉钉应用和审批模板
2. 运行同步命令获取数据
3. 执行测试脚本验证功能
4. 获取钉钉群ID
5. 配置定时任务
6. 监控首次正式发送
