# K3Cloud 日报关联功能 - UB 端部署说明

## 📝 部署步骤

### 1. 上传部署脚本到服务器

在本地执行：
```bash
scp deploy_to_ub.sh cenvy@172.16.77.80:~/dailyReport/
```

### 2. 登录服务器并执行部署

```bash
# SSH 登录
ssh cenvy@172.16.77.80

# 进入项目目录
cd ~/dailyReport

# 赋予执行权限
chmod +x deploy_to_ub.sh

# 执行部署脚本
./deploy_to_ub.sh
```

### 3. 验证部署

部署完成后，检查以下内容：

```bash
# 查看所有容器状态（应有 5 个容器运行）
docker-compose ps

# 预期输出：
# web       - running
# mailer    - running
# backup    - running
# sync      - running
# scheduler - running (新增)

# 查看 scheduler 日志
docker-compose logs scheduler | tail -50

# 测试近期同步
docker-compose exec web python manage.py sync_kingdee_recent --now --dry-run

# 测试报表生成
docker-compose exec web python manage.py generate_and_send_report --date 2026-10-04 --dry-run
```

---

## 🔧 手动部署步骤（如果脚本失败）

### 步骤 1: 拉取代码
```bash
cd ~/dailyReport
git pull
```

### 步骤 2: 备份数据库
```bash
docker-compose exec web python scripts/backup_sqlite.py
```

### 步骤 3: 重建容器
```bash
docker-compose down
docker-compose build
docker-compose up -d
```

### 步骤 4: 等待启动并应用迁移
```bash
sleep 30
docker-compose exec web python manage.py migrate integrations
```

### 步骤 5: 验证
```bash
docker-compose ps
docker-compose logs scheduler
```

---

## ⚙️ 配置说明

### 配置邮件收件组

进入 Django Admin 或使用 shell：

```bash
docker-compose exec web python manage.py shell
```

```python
from core.models import Company
from notifications.models import MailingList

company = Company.objects.first()

MailingList.objects.create(
    company=company,
    name="管理层日报",
    scope="BOTH",
    recipients="manager@company.com",
    send_at="08:30",
    attach_workbook=True,
    is_active=True,
)
```

### 配置钉钉群推送（可选）

```python
from integrations.models import DingtalkApp, DingtalkGroupConfig

app = DingtalkApp.objects.first()

DingtalkGroupConfig.objects.create(
    company=company,
    app=app,
    name="日报群",
    open_conversation_id="cidXXXXXXXX",  # 从钉钉获取
    scope="BOTH",
    send_at="09:00",
    is_active=True,
)
```

---

## 🔍 故障排查

### 容器无法启动

```bash
# 查看错误日志
docker-compose logs web
docker-compose logs scheduler

# 检查镜像
docker images | grep daily-report

# 强制重建
docker-compose build --no-cache
```

### 迁移失败

```bash
# 查看迁移状态
docker-compose exec web python manage.py showmigrations integrations

# 手动执行迁移
docker-compose exec web python manage.py migrate integrations --verbosity 2
```

### scheduler 容器未运行

```bash
# 查看容器日志
docker-compose logs scheduler

# 重启 scheduler
docker-compose restart scheduler

# 手工测试命令
docker-compose exec scheduler python manage.py sync_kingdee_recent --now
```

---

## 📊 监控命令

```bash
# 实时监控 scheduler 日志
docker-compose logs -f scheduler

# 查看最近 100 行日志
docker-compose logs --tail=100 scheduler

# 查看所有容器资源使用
docker stats

# 查看数据库大小
ls -lh data/db.sqlite3
```

---

## 🎯 验证功能

### 1. 访问日报录入页

浏览器打开：http://172.16.77.80:8001/sales/shipments/create/

检查：
- [ ] 页面正常加载
- [ ] "金蝶明细关联" 区域可见
- [ ] 展开后可以搜索

### 2. 测试 API

```bash
# 测试关联检索接口
curl -X POST http://172.16.77.80:8001/integrations/search-kingdee-lines/ \
  -H "Content-Type: application/json" \
  -d '{"company_id": 1, "business_type": "SALES_OUT"}'
```

### 3. 测试定时任务

```bash
# 查看 cron 日志
docker-compose logs scheduler | grep "sync_kingdee_recent\|generate_and_send_report"
```

---

## 📞 联系方式

如有问题，请查看：
- 完整实施报告_最终版_20261005.md
- K3Cloud 日报关联、金额对账与定时推送实施计划.md
