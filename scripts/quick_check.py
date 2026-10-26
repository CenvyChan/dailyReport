"""简单的功能验证脚本 - 无需交互。

直接运行: python scripts/quick_check.py
"""

import sys
import os
from pathlib import Path

# 添加项目根目录到路径
script_dir = Path(__file__).parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

# 初始化Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

try:
    import django
    django.setup()
except Exception as exc:
    print(f"[FAIL] Django初始化失败: {exc}")
    sys.exit(1)

print("=" * 60)
print("钉钉付款申请功能检查")
print("=" * 60)

# 1. 检查openpyxl
try:
    import openpyxl
    print(f"[OK] openpyxl: {openpyxl.__version__}")
except ImportError:
    print("[FAIL] openpyxl未安装,请运行: pip install openpyxl")
    sys.exit(1)

# 2. 检查模型导入
try:
    from integrations.models import DingtalkApp, DingtalkApprovalInstance
    from core.models import Company
    print("[OK] 模型导入成功")
except Exception as exc:
    print(f"[FAIL] 模型导入失败: {exc}")
    sys.exit(1)

# 3. 检查服务模块
try:
    from integrations.services import payment_report, payment_excel, payment_message
    print("[OK] 服务模块导入成功")
except Exception as exc:
    print(f"[FAIL] 服务模块导入失败: {exc}")
    sys.exit(1)

# 4. 检查管理命令
try:
    from django.core.management import call_command
    # 测试命令是否可被发现
    from django.core.management import get_commands
    commands = get_commands()
    if 'sync_payment_approvals' in commands:
        print("[OK] sync_payment_approvals 命令已注册")
    else:
        print("[WARN] sync_payment_approvals 命令未找到")

    if 'send_payment_report' in commands:
        print("[OK] send_payment_report 命令已注册")
    else:
        print("[WARN] send_payment_report 命令未找到")
except Exception as exc:
    print(f"[FAIL] 命令检查失败: {exc}")

# 5. 检查配置
companies = Company.objects.filter(dingtalk_app__is_active=True).distinct()
print(f"\n配置状态:")
print(f"  启用钉钉的公司数: {companies.count()}")

if companies.count() > 0:
    for company in companies:
        print(f"  - {company.name} ({company.code})")

# 6. 检查数据
approval_count = DingtalkApprovalInstance.objects.count()
print(f"  审批实例总数: {approval_count}")

if approval_count > 0:
    recent = DingtalkApprovalInstance.objects.order_by('-create_time').first()
    if recent:
        print(f"  最新审批: {recent.title or recent.process_instance_id}")
        print(f"  创建时间: {recent.create_time}")

# 7. 测试时间范围计算
try:
    from integrations.services.payment_report import get_last_week_range, get_last_month_range
    week_period = get_last_week_range()
    month_period = get_last_month_range()
    print(f"\n时间范围测试:")
    print(f"  上周: {week_period['label']}")
    print(f"  上月: {month_period['label']}")
except Exception as exc:
    print(f"[FAIL] 时间范围计算失败: {exc}")

print("\n" + "=" * 60)
print("检查完成!")
print("=" * 60)

print("\n下一步:")
if companies.count() == 0:
    print("  1. 在Django Admin中配置 integrations.DingtalkApp")
    print("  2. 运行: python manage.py sync_payment_approvals")
elif approval_count == 0:
    print("  1. 运行: python manage.py sync_payment_approvals")
    print("  2. 测试: python manage.py send_payment_report week --dry-run")
else:
    print("  1. 测试报表生成:")
    print("     python manage.py send_payment_report week --dry-run --output-dir ./test_reports")
    print("  2. 获取钉钉群ID后发送:")
    print("     python manage.py send_payment_report week --group-id <openConversationId>")
