# UB端 - 付款申请功能部署与测试指南

## 📦 Docker部署步骤

### 1. 拉取最新代码

```bash
cd /path/to/dailyReport
git pull origin main
```

**验证新功能代码**：
```bash
# 确认新增文件存在
ls -la integrations/services/payment_*.py
ls -la integrations/management/commands/*payment*.py
ls -la docs/payment_report_*.md
```

### 2. 重新构建Docker镜像

```bash
# 停止现有容器
docker-compose down

# 重新构建镜像（包含新代码）
docker-compose build --no-cache

# 启动容器
docker-compose up -d
```

**说明**：
- `--no-cache`：确保使用最新代码构建
- `-d`：后台运行

### 3. 检查容器状态

```bash
# 查看容器运行状态
docker-compose ps

# 查看Django容器日志
docker-compose logs -f web

# 应该看到类似：
# Starting development server at http://0.0.0.0:8000/
# Quit the server with CONTROL-C.
```

### 4. 进入容器检查功能

```bash
# 进入Django容器
docker-compose exec web bash

# 快速检查功能
python scripts/quick_check.py

# 查看管理命令是否注册
python manage.py help | grep payment

# 预期输出：
#   send_payment_report
#   sync_payment_approvals
```

## 🔧 UB端配置

### 1. 访问Django Admin

浏览器访问: `http://<UB服务器IP>:8000/admin/`

使用超级管理员账户登录。

### 2. 配置钉钉应用

路径: **INTEGRATIONS → 钉钉应用 → 添加钉钉应用**

填写以下信息（你说已经配置好了）：
- 公司: FNS
- 应用名称: 付款申请机器人
- AppKey: [你已配置的值]
- AppSecret: [你已配置的值]
- CorpId: [你已配置的值]
- AgentId: [你已配置的值]
- 启用: ✓

**保存后测试连接**：
```bash
docker-compose exec web python manage.py shell
>>> from integrations.models import DingtalkApp
>>> from integrations.services.dingtalk_client import DingtalkClient
>>> app = DingtalkApp.objects.first()
>>> client = DingtalkClient(app)
>>> token = client.token()
>>> print(f"Token获取成功: {token[:20]}...")
>>> exit()
```

### 3. 配置审批模板

路径: **INTEGRATIONS → 钉钉审批模板 → 添加钉钉审批模板**

填写：
- 钉钉应用: [选择刚创建的应用]
- 审批模板Code: `PROC-80780FFA-3A5F-436B-BC53-14CC357AAC0C`
- 模板名称: `付款申请`
- 金额组件名: `付款总额`
- 回看天数: `30`
- 启用: ✓

**如何获取审批模板Code**：
1. 登录钉钉管理后台: https://oa.dingtalk.com
2. 工作台 → 审批 → 找到"付款申请"模板
3. 点击进入模板详情，URL中包含 `process_code=PROC-XXX`
4. 复制这个Code到配置中

## 🧪 UB端测试流程

### 测试1: 数据同步验证

```bash
# 进入容器
docker-compose exec web bash

# 首次同步（回看30天）
python manage.py sync_payment_approvals --lookback-days 30

# 预期输出：
# [INFO] 开始同步付款申请审批...
# [INFO] 找到 1 个付款申请模板配置
# [INFO] 查询时间范围: 2026-09-26 到 2026-10-26
# [INFO] 找到 X 个审批实例
# [INFO] 新增: X, 更新: X, 无变化: X
# [SUCCESS] 同步完成
```

**验证数据**：
```bash
python manage.py shell
>>> from integrations.models import DingtalkApprovalInstance
>>> count = DingtalkApprovalInstance.objects.count()
>>> print(f"已同步审批数量: {count}")
>>> 
>>> # 查看最新的5条
>>> for inst in DingtalkApprovalInstance.objects.order_by('-create_time')[:5]:
...     print(f"{inst.title} | {inst.biz_action} | {inst.amount_cny}")
>>> exit()
```

### 测试2: Excel报表生成

```bash
# Dry-run模式（仅生成Excel，不发送）
python manage.py send_payment_report week \
  --dry-run \
  --output-dir /app/test_reports

# 预期输出：
# [INFO] 周报时间范围: 2026-10-20 ~ 2026-10-26
# [INFO] 找到 X 条审批记录
# [INFO] 按收款人汇总: X 个收款人
# [INFO] Excel已生成: /app/test_reports/付款申请周报_XXX.xlsx
# [DRY-RUN] 跳过钉钉推送
```

**下载Excel验证**：
```bash
# 从容器复制到宿主机
docker cp $(docker-compose ps -q web):/app/test_reports/付款申请周报_*.xlsx ./

# 或者在容器内直接查看
ls -lh /app/test_reports/
```

**Excel内容检查**：
- 工作表1: 汇总统计（总数/总金额/按状态分类）
- 工作表2: 按收款人汇总（TOP收款人）
- 工作表3: 详细清单（逐条审批明细）
- 工作表4: 原始JSON（调试用）

### 测试3: 钉钉群ID获取

**方法1: 钉钉管理后台**
1. 登录 https://oa.dingtalk.com
2. 找到目标群（如"财务部-付款申请周报"）
3. 群设置 → 查看openConversationId

**方法2: 使用API查询**（需要管理员权限）
```bash
docker-compose exec web python manage.py shell
>>> from integrations.models import DingtalkApp
>>> from integrations.services.dingtalk_client import DingtalkClient
>>> app = DingtalkApp.objects.first()
>>> client = DingtalkClient(app)
>>> # 注意：需要有获取群列表的权限
>>> # 如果没有权限，请使用方法1
```

### 测试4: 钉钉消息推送测试

**先创建测试群**（推荐）：
1. 在钉钉创建一个测试群（如"付款申请功能测试"）
2. 添加机器人到群（或使用应用发送）
3. 获取测试群的openConversationId

```bash
# 在测试群发送周报
docker-compose exec web python manage.py send_payment_report week \
  --company FNS \
  --group-id <测试群openConversationId>

# 预期输出：
# [INFO] 周报时间范围: 2026-10-20 ~ 2026-10-26
# [INFO] 找到 X 条审批记录
# [INFO] Excel已生成: /tmp/付款申请周报_XXX.xlsx
# [INFO] 开始推送到钉钉群: <测试群openConversationId>
# [SUCCESS] 消息推送成功
```

**检查钉钉群消息**：
- 统计摘要（总计/已完成/进行中）
- 按收款人分组（前10个）
- 每个收款人的前5条明细
- Excel报表下载链接
- @相关用户（如果配置）

### 测试5: 历史数据测试

使用 `--base-date` 参数测试历史周期：

```bash
# 测试上上周的数据（2026-10-07 ~ 2026-10-13）
docker-compose exec web python manage.py send_payment_report week \
  --base-date 2026-10-13 \
  --dry-run \
  --output-dir /app/test_reports

# 测试上月的数据（2026年9月）
docker-compose exec web python manage.py send_payment_report month \
  --base-date 2026-09-30 \
  --dry-run \
  --output-dir /app/test_reports
```

### 测试6: 增量同步测试

```bash
# 第一次同步
docker-compose exec web python manage.py sync_payment_approvals

# 记录同步结果
# 新增: A, 更新: B

# 等待几分钟（模拟审批状态变化）

# 第二次同步（应该只更新变更的）
docker-compose exec web python manage.py sync_payment_approvals

# 预期输出：
# 新增: 0~少量, 更新: 变更的数量
```

## 📅 定时任务配置

### 使用cron（推荐）

```bash
# 编辑crontab
crontab -e

# 添加以下任务：

# 每日20:00同步审批数据
0 20 * * * cd /path/to/dailyReport && docker-compose exec -T web python manage.py sync_payment_approvals >> /var/log/dailyReport/sync_payment.log 2>&1

# 每周一09:00发送周报
0 9 * * 1 cd /path/to/dailyReport && docker-compose exec -T web python manage.py send_payment_report week --company FNS --group-id <群ID> >> /var/log/dailyReport/weekly_report.log 2>&1

# 每月1日09:00发送月报
0 9 1 * * cd /path/to/dailyReport && docker-compose exec -T web python manage.py send_payment_report month --company FNS --group-id <群ID> >> /var/log/dailyReport/monthly_report.log 2>&1
```

**注意**：
- 将 `<群ID>` 替换为实际的openConversationId
- 将 `/path/to/dailyReport` 替换为实际路径
- 确保日志目录存在: `mkdir -p /var/log/dailyReport`

### 使用Docker容器内cron

如果你的Dockerfile支持cron，可以在容器内配置：

```bash
# 进入容器
docker-compose exec web bash

# 安装cron（如果没有）
apt-get update && apt-get install -y cron

# 创建cron任务文件
cat > /etc/cron.d/payment-report << 'EOF'
# 每日20:00同步
0 20 * * * root cd /app && python manage.py sync_payment_approvals >> /var/log/sync.log 2>&1

# 每周一09:00周报
0 9 * * 1 root cd /app && python manage.py send_payment_report week --company FNS --group-id <群ID> >> /var/log/weekly.log 2>&1

# 每月1日09:00月报
0 9 1 * * root cd /app && python manage.py send_payment_report month --company FNS --group-id <群ID> >> /var/log/monthly.log 2>&1
EOF

# 设置权限
chmod 0644 /etc/cron.d/payment-report

# 启动cron
service cron start
```

## 🔍 故障排查

### 问题1: 命令找不到

```bash
docker-compose exec web python manage.py help | grep payment
# 如果没有输出，检查：
# 1. 代码是否正确pull
# 2. 容器是否重新构建
# 3. integrations/management/commands/ 目录是否存在 __init__.py
```

### 问题2: 同步无数据

```bash
# 检查配置
docker-compose exec web python manage.py shell
>>> from integrations.models import DingtalkProcessConfig
>>> configs = DingtalkProcessConfig.objects.filter(is_active=True)
>>> for c in configs:
...     print(f"{c.app.company} | {c.process_code} | {c.template_name}")

# 手动强制同步
docker-compose exec web python manage.py sync_payment_approvals --force --lookback-days 60
```

### 问题3: 钉钉推送失败

```bash
# 测试Token获取
docker-compose exec web python manage.py shell
>>> from integrations.models import DingtalkApp
>>> from integrations.services.dingtalk_client import DingtalkClient
>>> app = DingtalkApp.objects.first()
>>> client = DingtalkClient(app)
>>> token = client.token()
>>> print(token)  # 应该返回一个access_token

# 检查群ID是否正确
# openConversationId格式: cidXXXXXXXXXXXXXXXXXXX
```

### 问题4: Excel生成失败

```bash
# 检查openpyxl
docker-compose exec web python -c "import openpyxl; print(openpyxl.__version__)"
# 应该输出: 3.1.5 或更高

# 如果缺失，安装
docker-compose exec web pip install openpyxl==3.1.5
```

### 问题5: 容器内时区不对

```bash
# 检查时区
docker-compose exec web date

# 如果不是Asia/Shanghai，在docker-compose.yml添加：
# environment:
#   - TZ=Asia/Shanghai

# 重启容器
docker-compose restart
```

## 📊 监控和日志

### 查看实时日志

```bash
# Django应用日志
docker-compose logs -f web

# 同步任务日志
docker-compose exec web tail -f /app/logs/integrations.log

# 报表推送日志
docker-compose exec web tail -f /app/logs/notifications.log
```

### 检查执行历史

```bash
# 查看最近的同步记录
docker-compose exec web python manage.py shell
>>> from integrations.models import DingtalkApprovalInstance
>>> from django.utils import timezone
>>> from datetime import timedelta
>>> 
>>> # 最近24小时同步的记录
>>> recent = DingtalkApprovalInstance.objects.filter(
...     updated_at__gte=timezone.now() - timedelta(days=1)
... ).count()
>>> print(f"最近24小时更新: {recent} 条")
```

## ✅ 部署验证清单

部署完成后，按此清单验证：

- [ ] 代码已pull到最新版本（ea4211e或更新）
- [ ] Docker容器已重新构建并启动
- [ ] 快速检查脚本通过: `python scripts/quick_check.py`
- [ ] 管理命令已注册: `python manage.py help | grep payment`
- [ ] Django Admin已配置钉钉应用和审批模板
- [ ] Token获取测试通过
- [ ] 首次数据同步成功（有记录）
- [ ] Dry-run测试生成Excel成功
- [ ] 获取到正式群openConversationId
- [ ] 测试群推送成功（消息+Excel）
- [ ] 正式群推送成功（消息+Excel）
- [ ] 定时任务已配置（cron）
- [ ] 日志目录已创建且可写

## 📞 技术支持

- 快速检查: `docker-compose exec web python scripts/quick_check.py`
- 详细文档: `docs/README_payment_report.md`
- 实施清单: `docs/payment_report_checklist.md`
- 日志位置: `/app/logs/integrations.log`

---

**最后更新**: 2026-10-26  
**Git Commit**: ea4211e  
**功能版本**: v1.0
