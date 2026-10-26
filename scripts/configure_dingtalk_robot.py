#!/usr/bin/env python
"""
钉钉群机器人配置助手

帮助获取和配置钉钉群机器人的 robotCode 和群 openConversationId。
"""

import sys
import django

# Django 初始化
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from integrations.models import DingtalkApp
from integrations.services.dingtalk_client import DingtalkClient


def list_robots(client):
    """列出应用下的所有机器人。"""
    print("\n" + "=" * 60)
    print("查询应用下的机器人...")
    print("=" * 60)

    try:
        result = client.get('/v1.0/robot/orgRobots')
        robots = result.get('result', {}).get('list', [])

        if not robots:
            print("❌ 未找到任何机器人")
            print("\n请先在钉钉开放平台创建群机器人：")
            print("  1. 登录 https://open-dev.dingtalk.com")
            print("  2. 进入应用 → 机器人与消息 → 群机器人")
            print("  3. 创建新的群机器人")
            return None

        print(f"\n✓ 找到 {len(robots)} 个机器人:\n")
        for idx, robot in enumerate(robots, 1):
            print(f"{idx}. {robot.get('name', '未命名')}")
            print(f"   robotCode: {robot.get('robotCode')}")
            print(f"   描述: {robot.get('brief', '无')}")
            print()

        return robots
    except Exception as e:
        print(f"❌ 查询机器人失败: {e}")
        return None


def list_groups(client, robot_code):
    """列出机器人加入的所有群。"""
    print("\n" + "=" * 60)
    print(f"查询机器人 {robot_code} 加入的群...")
    print("=" * 60)

    try:
        result = client.post('/v1.0/robot/groupsOfRobot', {
            'robotCode': robot_code,
            'maxResults': 50,
        })

        groups = result.get('result', {}).get('groupInfos', [])

        if not groups:
            print("❌ 机器人未加入任何群")
            print("\n请将机器人添加到目标群：")
            print("  1. 在钉钉手机端打开目标群")
            print("  2. 群设置 → 群机器人 → 添加机器人")
            print("  3. 选择你的自定义机器人")
            return None

        print(f"\n✓ 机器人已加入 {len(groups)} 个群:\n")
        for idx, group in enumerate(groups, 1):
            print(f"{idx}. {group.get('name', '未命名群')}")
            print(f"   openConversationId: {group.get('openConversationId')}")
            print(f"   群主: {group.get('ownerName', '未知')}")
            print()

        return groups
    except Exception as e:
        print(f"❌ 查询群列表失败: {e}")
        return None


def configure_robot_code(app, robot_code):
    """配置机器人 Code 到数据库。"""
    print("\n" + "=" * 60)
    print("配置机器人 Code...")
    print("=" * 60)

    old_code = app.robot_code
    app.robot_code = robot_code
    app.save()

    print(f"\n✓ 配置成功!")
    if old_code:
        print(f"  旧值: {old_code}")
    print(f"  新值: {robot_code}")
    print(f"  公司: {app.company.name} ({app.company.code})")


def main():
    print("=" * 60)
    print("钉钉群机器人配置助手")
    print("=" * 60)

    # 获取钉钉应用
    apps = DingtalkApp.objects.filter(is_active=True)

    if not apps.exists():
        print("\n❌ 未找到启用的钉钉应用")
        print("请先在 Django Admin 中配置 DingtalkApp")
        return

    if apps.count() > 1:
        print("\n选择要配置的钉钉应用:")
        for idx, app in enumerate(apps, 1):
            print(f"{idx}. {app.company.name} - {app.name or '未命名'}")
            if app.robot_code:
                print(f"   当前 robot_code: {app.robot_code}")

        choice = input("\n请输入序号: ").strip()
        try:
            app = list(apps)[int(choice) - 1]
        except (ValueError, IndexError):
            print("❌ 无效的选择")
            return
    else:
        app = apps.first()

    print(f"\n当前应用: {app.company.name} - {app.name or '未命名'}")
    if app.robot_code:
        print(f"已配置 robot_code: {app.robot_code}")

    # 创建客户端
    try:
        client = DingtalkClient(app)
    except Exception as e:
        print(f"\n❌ 初始化钉钉客户端失败: {e}")
        print("请检查 app_key 和 app_secret 配置")
        return

    # 列出机器人
    robots = list_robots(client)
    if not robots:
        return

    # 选择机器人
    if len(robots) == 1:
        robot = robots[0]
        robot_code = robot['robotCode']
        print(f"使用唯一的机器人: {robot.get('name')} ({robot_code})")
    else:
        choice = input("\n请选择要配置的机器人序号: ").strip()
        try:
            robot = robots[int(choice) - 1]
            robot_code = robot['robotCode']
        except (ValueError, IndexError):
            print("❌ 无效的选择")
            return

    # 配置到数据库
    if app.robot_code != robot_code:
        confirm = input(f"\n确认配置 robot_code 为 {robot_code}? (y/n): ").strip().lower()
        if confirm == 'y':
            configure_robot_code(app, robot_code)
        else:
            print("❌ 已取消")
            return
    else:
        print(f"\n✓ robot_code 已是 {robot_code}，无需更新")

    # 列出群
    groups = list_groups(client, robot_code)
    if not groups:
        return

    # 提示如何使用
    print("\n" + "=" * 60)
    print("配置完成！使用示例：")
    print("=" * 60)

    group_id = groups[0]['openConversationId']
    print(f"\n# 测试周报（dry-run）")
    print(f"docker exec daily-report-web python manage.py send_payment_report week \\")
    print(f"  --dry-run \\")
    print(f"  --output-dir /app/data")

    print(f"\n# 发送周报到第一个群")
    print(f"docker exec daily-report-web python manage.py send_payment_report week \\")
    print(f"  --group-id \"{group_id}\"")

    print(f"\n# 发送月报到第一个群")
    print(f"docker exec daily-report-web python manage.py send_payment_report month \\")
    print(f"  --group-id \"{group_id}\"")

    print("\n详细文档: docs/钉钉付款申请周报月报配置指南.md")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n已取消")
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
