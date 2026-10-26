#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""钉钉付款申请报表快速测试脚本。

在正式配置定时任务前,使用本脚本快速验证功能:
1. 检查环境依赖
2. 验证配置
3. 生成测试报表
4. (可选)发送测试消息

使用方法:
    cd E:\\DEV\\dailyReport
    python scripts\\test_payment_report.py
"""

import sys
import os
from pathlib import Path

# 设置UTF-8输出(Windows兼容)
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 添加项目根目录到路径
script_dir = Path(__file__).parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

# 切换工作目录到项目根目录
os.chdir(project_root)

# 初始化Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

try:
    import django
    django.setup()
except Exception as exc:
    print(f"Django初始化失败: {exc}")
    print(f"当前工作目录: {os.getcwd()}")
    print(f"项目根目录: {project_root}")
    print(f"Python路径: {sys.path[:3]}")
    print("\n请确保:")
    print("  1. 在项目根目录运行: cd E:\\DEV\\dailyReport")
    print("  2. 已安装Django: pip install -r requirements.txt")
    sys.exit(1)

from datetime import datetime
from django.core.management import call_command
from integrations.models import DingtalkApp, DingtalkProcessConfig
from core.models import Company


def check_dependencies():
    """检查依赖是否已安装。"""
    print("=" * 60)
    print("检查依赖...")
    print("=" * 60)

    missing = []

    # 检查openpyxl
    try:
        import openpyxl
        print(f"[OK] openpyxl: {openpyxl.__version__}")
    except ImportError:
        print("[FAIL] openpyxl 未安装")
        missing.append('openpyxl')

    # 检查Django相关
    try:
        import django
        print(f"[OK] Django: {django.__version__}")
    except ImportError:
        print("[FAIL] Django 未安装")
        missing.append('django')

    if missing:
        print(f"\n缺少依赖: {', '.join(missing)}")
        print(f"请运行: pip install {' '.join(missing)}")
        return False

    print("\n[OK] 所有依赖已安装")
    return True


def check_configuration():
    """检查钉钉配置。"""
    print("\n" + "=" * 60)
    print("检查配置...")
    print("=" * 60)

    # 检查公司
    companies = Company.objects.filter(dingtalk_app__is_active=True).distinct()
    if not companies:
        print("[FAIL] 没有启用钉钉应用的公司")
        print("  请在Django Admin中配置 integrations.DingtalkApp")
        return False

    print(f"[OK] 找到 {companies.count()} 个启用钉钉的公司:")
    for company in companies:
        print(f"  - {company.name} ({company.code})")

    # 检查审批模板
    for company in companies:
        try:
            app = company.dingtalk_app
            print(f"\n公司 {company.code} 的配置:")
            print(f"  AppKey: {app.app_key[:10]}...")
            print(f"  CorpId: {app.corp_id or '(未配置)'}")
            print(f"  AgentId: {app.agent_id or '(未配置)'}")

            # 检查审批模板
            process_configs = DingtalkProcessConfig.objects.filter(
                app=app,
                is_active=True,
                name__icontains='付款申请'
            )

            if process_configs.exists():
                print(f"  [OK] 付款申请模板:")
                for config in process_configs:
                    print(f"    - {config.name} ({config.process_code})")
            else:
                print(f"  [WARN] 未配置付款申请审批模板")

        except Exception as exc:
            print(f"  [FAIL] 配置读取失败: {exc}")
            return False

    return True


def check_approval_data():
    """检查审批数据。"""
    print("\n" + "=" * 60)
    print("检查审批数据...")
    print("=" * 60)

    from integrations.models import DingtalkApprovalInstance

    companies = Company.objects.filter(dingtalk_app__is_active=True)

    has_data = False
    for company in companies:
        count = DingtalkApprovalInstance.objects.filter(company=company).count()
        print(f"{company.code}: {count} 条审批实例")
        if count > 0:
            has_data = True

            # 显示最近的审批
            recent = DingtalkApprovalInstance.objects.filter(
                company=company
            ).order_by('-create_time').first()

            if recent:
                print(f"  最新审批: {recent.title or recent.process_instance_id}")
                print(f"  发起时间: {recent.create_time}")
                print(f"  状态: {recent.status}")

    if not has_data:
        print("\n[WARN] 没有审批数据")
        print("  请先运行: python manage.py sync_dingtalk")
        return False

    print("\n[OK] 审批数据已就绪")
    return True


def generate_test_report(company_code=None, output_dir='./test_reports'):
    """生成测试报表。"""
    print("\n" + "=" * 60)
    print("生成测试报表...")
    print("=" * 60)

    args = ['week', '--output-dir', output_dir, '--dry-run']
    if company_code:
        args.extend(['--company', company_code])

    try:
        call_command('send_payment_report', *args)
        print(f"\n[OK] 测试报表已生成,请查看: {output_dir}")
        return True
    except Exception as exc:
        print(f"\n[FAIL] 生成失败: {exc}")
        import traceback
        traceback.print_exc()
        return False


def interactive_test():
    """交互式测试。"""
    print("\n" + "=" * 60)
    print("交互式测试")
    print("=" * 60)

    # 选择公司
    companies = list(Company.objects.filter(dingtalk_app__is_active=True))
    if not companies:
        print("没有可用的公司")
        return

    print("\n选择公司:")
    for idx, company in enumerate(companies, 1):
        print(f"  {idx}. {company.name} ({company.code})")

    try:
        choice = int(input("\n请输入序号 [1]: ") or "1")
        company = companies[choice - 1]
    except (ValueError, IndexError):
        print("无效选择,使用第一个公司")
        company = companies[0]

    print(f"\n已选择: {company.name} ({company.code})")

    # 选择报表类型
    print("\n选择报表类型:")
    print("  1. 周报(上周)")
    print("  2. 月报(上月)")

    try:
        choice = int(input("\n请输入序号 [1]: ") or "1")
        report_type = 'week' if choice == 1 else 'month'
    except ValueError:
        report_type = 'week'

    # 是否发送
    send = input("\n是否发送到钉钉群? (y/N): ").lower() == 'y'

    if send:
        group_id = input("请输入群ID(openConversationId): ").strip()
        if not group_id:
            print("未输入群ID,仅生成报表")
            send = False

    # 生成报表
    args = [report_type, '--company', company.code]

    if send:
        args.extend(['--group-id', group_id])
    else:
        args.extend(['--output-dir', './test_reports', '--dry-run'])

    try:
        print("\n执行命令:", 'send_payment_report', ' '.join(args))
        call_command('send_payment_report', *args)
        print("\n[OK] 完成")
    except Exception as exc:
        print(f"\n[FAIL] 失败: {exc}")
        import traceback
        traceback.print_exc()


def main():
    """主函数。"""
    print("\n" + "=" * 60)
    print("钉钉付款申请报表 - 快速测试")
    print("=" * 60)

    # 1. 检查依赖
    if not check_dependencies():
        sys.exit(1)

    # 2. 检查配置
    if not check_configuration():
        print("\n[WARN] 配置不完整,但可以继续测试基本功能")

    # 3. 检查数据
    check_approval_data()

    # 4. 选择测试方式
    print("\n" + "=" * 60)
    print("选择测试方式:")
    print("=" * 60)
    print("  1. 快速测试(生成所有公司的周报,不发送)")
    print("  2. 交互式测试(选择公司和报表类型)")
    print("  3. 退出")

    try:
        choice = int(input("\n请输入序号 [1]: ") or "1")
    except ValueError:
        choice = 1

    if choice == 1:
        generate_test_report()
    elif choice == 2:
        interactive_test()
    else:
        print("退出")

    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)
    print("\n后续步骤:")
    print("  1. 检查生成的Excel报表: ./test_reports/")
    print("  2. 确认数据正确后,获取钉钉群ID")
    print("  3. 测试发送: python manage.py send_payment_report week --group-id <群ID>")
    print("  4. 配置定时任务(参见 docs/payment_report_guide.md)")
    print("\n")


if __name__ == '__main__':
    main()
