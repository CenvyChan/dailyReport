#!/bin/bash
# K3Cloud 日报关联功能部署脚本
# 在 UB 端 (172.16.77.80) 执行

set -e

echo "=================================="
echo "K3Cloud 日报关联功能部署"
echo "=================================="

# 1. 拉取最新代码
echo "📥 拉取最新代码..."
git pull

# 2. 检查当前容器状态
echo ""
echo "📊 当前容器状态："
docker-compose ps

# 3. 备份数据库
echo ""
echo "💾 备份数据库..."
docker-compose exec -T web python scripts/backup_sqlite.py || true

# 4. 停止所有容器
echo ""
echo "🛑 停止所有容器..."
docker-compose down

# 5. 重新构建镜像
echo ""
echo "🔨 重新构建镜像..."
docker-compose build

# 6. 启动所有容器
echo ""
echo "🚀 启动所有容器..."
docker-compose up -d

# 7. 等待容器启动
echo ""
echo "⏳ 等待容器启动（30秒）..."
sleep 30

# 8. 应用数据库迁移
echo ""
echo "📦 应用数据库迁移..."
docker-compose exec -T web python manage.py migrate integrations

# 9. 检查迁移状态
echo ""
echo "✅ 检查迁移状态："
docker-compose exec -T web python manage.py showmigrations integrations

# 10. 查看新容器状态
echo ""
echo "📊 新容器状态："
docker-compose ps

# 11. 查看最近日志
echo ""
echo "📝 scheduler 容器日志（最近 20 行）："
docker-compose logs --tail=20 scheduler

echo ""
echo "=================================="
echo "✅ 部署完成！"
echo "=================================="
echo ""
echo "📋 后续步骤："
echo "1. 配置邮件收件组（Django Admin）"
echo "2. 配置钉钉群推送（可选）"
echo "3. 重新同步历史数据："
echo "   docker-compose exec web python manage.py sync_kingdee --from 2026-01 --to 2026-10"
echo ""
echo "📖 查看完整文档："
echo "   cat 完整实施报告_最终版_20261005.md"
echo ""
echo "🔍 监控 scheduler 日志："
echo "   docker-compose logs -f scheduler"
echo ""
