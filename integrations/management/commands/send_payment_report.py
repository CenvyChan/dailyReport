"""发送钉钉付款申请周报/月报。

汇总已同步的付款申请审批实例,生成Excel报表,并推送到钉钉群。
建议定时任务:
- 周报: 每周一早上 09:00 运行 send_payment_report week
- 月报: 每月1日早上 09:00 运行 send_payment_report month
"""

import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import Company
from integrations.models import DingtalkApp, DingtalkProcessConfig
from integrations.services.dingtalk_client import DingtalkClient
from integrations.services.payment_excel import generate_payment_excel
from integrations.services.payment_message import build_payment_report_message
from integrations.services.payment_report import (
    analyze_payment_applications,
    get_last_month_range,
    get_last_week_range,
)

logger = logging.getLogger("integrations")


class Command(BaseCommand):
    help = "发送钉钉付款申请周报/月报到指定群"

    def add_arguments(self, parser):
        parser.add_argument(
            'report_type',
            choices=['week', 'month'],
            help="报表类型: week(周报) 或 month(月报)"
        )
        parser.add_argument(
            '--company',
            help="公司代码,默认发送所有启用钉钉的公司"
        )
        parser.add_argument(
            '--group-id',
            dest='group_id',
            help="钉钉群ID(openConversationId),不指定则读取配置"
        )
        parser.add_argument(
            '--process-code',
            dest='process_code',
            help="审批模板Code,不指定则使用配置中的付款申请模板"
        )
        parser.add_argument(
            '--base-date',
            dest='base_date',
            help="基准日期(YYYY-MM-DD),默认今天。用于测试历史数据"
        )
        parser.add_argument(
            '--output-dir',
            dest='output_dir',
            help="Excel输出目录,默认为临时目录"
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help="仅生成Excel不发送"
        )
        parser.add_argument(
            '--mention',
            nargs='+',
            help="要@的用户ID列表(空格分隔)"
        )
        parser.add_argument(
            '--no-card',
            action='store_true',
            help="强制使用文本消息,不使用互动卡片"
        )

    def handle(self, *args, **options):
        report_type = options['report_type']

        # 解析基准日期
        base_date = None
        if options['base_date']:
            try:
                base_date = datetime.strptime(options['base_date'], '%Y-%m-%d').date()
            except ValueError as exc:
                raise CommandError(f"日期格式应为 YYYY-MM-DD: {exc}") from exc

        # 获取时间范围
        if report_type == 'week':
            period_info = get_last_week_range(base_date)
            self.stdout.write(f"生成周报: {period_info['label']}")
        else:
            period_info = get_last_month_range(base_date)
            self.stdout.write(f"生成月报: {period_info['label']}")

        # 确定要处理的公司
        if options['company']:
            try:
                companies = [Company.objects.get(code=options['company'])]
            except Company.DoesNotExist as exc:
                raise CommandError(f"找不到公司代码: {options['company']}") from exc
        else:
            # 获取所有启用钉钉应用的公司
            companies = Company.objects.filter(
                dingtalk_app__is_active=True
            ).distinct()

        if not companies:
            self.stdout.write(self.style.WARNING("没有启用钉钉应用的公司"))
            return

        # 准备输出目录
        if options['output_dir']:
            output_dir = Path(options['output_dir'])
            output_dir.mkdir(parents=True, exist_ok=True)
        else:
            output_dir = Path(tempfile.gettempdir()) / 'payment_reports'
            output_dir.mkdir(parents=True, exist_ok=True)

        success_count = 0
        error_count = 0

        # 逐公司处理
        for company in companies:
            try:
                self.stdout.write(f"\n处理公司: {company.name} ({company.code})")

                # 获取钉钉应用
                try:
                    dingtalk_app = company.dingtalk_app
                except DingtalkApp.DoesNotExist:
                    self.stdout.write(self.style.WARNING(f"  跳过: 未配置钉钉应用"))
                    continue

                if not dingtalk_app.is_active:
                    self.stdout.write(self.style.WARNING(f"  跳过: 钉钉应用未启用"))
                    continue

                # 获取审批模板
                process_code = options.get('process_code')
                if not process_code:
                    try:
                        # 查找名为"付款申请"的模板
                        process_config = DingtalkProcessConfig.objects.filter(
                            app=dingtalk_app,
                            is_active=True,
                            name__icontains='付款申请'
                        ).first()
                        if process_config:
                            process_code = process_config.process_code
                        else:
                            self.stdout.write(self.style.WARNING(
                                f"  跳过: 未配置付款申请审批模板,请使用 --process-code 指定"
                            ))
                            continue
                    except Exception as exc:
                        self.stdout.write(self.style.WARNING(
                            f"  跳过: 查询审批模板失败: {exc}"
                        ))
                        continue

                self.stdout.write(f"  审批模板: {process_code}")

                # 汇总数据
                self.stdout.write(f"  汇总付款申请...")
                data = analyze_payment_applications(
                    company,
                    period_info['start'],
                    period_info['end'],
                    process_code
                )

                total_count = data['summary']['total_count']
                total_amount = data['summary']['total_amount']
                self.stdout.write(
                    f"  找到 {total_count} 条付款申请, "
                    f"总金额 ¥{float(total_amount):,.2f}"
                )

                # 生成Excel
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                excel_filename = (
                    f"付款申请{'周报' if report_type == 'week' else '月报'}_"
                    f"{company.code}_{timestamp}.xlsx"
                )
                excel_path = output_dir / excel_filename

                self.stdout.write(f"  生成Excel: {excel_path}")
                generate_payment_excel(data, period_info, str(excel_path))

                if options['dry_run']:
                    self.stdout.write(self.style.SUCCESS(
                        f"  ✓ Dry-run模式,Excel已生成,未发送消息"
                    ))
                    success_count += 1
                    continue

                # 发送到钉钉群
                group_id = options.get('group_id')
                if not group_id:
                    # 从配置读取(这里暂时需要手动配置,后续可扩展模型)
                    self.stdout.write(self.style.WARNING(
                        f"  跳过发送: 未指定群ID,请使用 --group-id 参数"
                    ))
                    continue

                # 检查机器人配置
                if not dingtalk_app.robot_code:
                    self.stdout.write(self.style.WARNING(
                        f"  跳过发送: 未配置机器人Code,请在Django Admin中配置 DingtalkApp.robot_code"
                    ))
                    continue

                self.stdout.write(f"  发送到钉钉群: {group_id}")

                # 上传Excel
                client = DingtalkClient(dingtalk_app)
                with open(excel_path, 'rb') as f:
                    excel_content = f.read()

                media_id = client.upload_media(excel_filename, excel_content)
                self.stdout.write(f"  Excel已上传, media_id: {media_id}")

                # 判断使用卡片还是文本消息
                use_card = bool(dingtalk_app.card_template_id) and not options.get('no_card')

                if use_card:
                    self.stdout.write("  使用互动卡片发送")
                    from integrations.services.payment_card import (
                        build_payment_card_data,
                        send_interactive_card,
                    )

                    # 生成卡片数据
                    card_data = build_payment_card_data(data, period_info, report_type)

                    # 发送卡片
                    try:
                        card_result = send_interactive_card(
                            client,
                            group_id,
                            card_data,
                            dingtalk_app.card_template_id
                        )
                        self.stdout.write(f"  互动卡片已发送: {card_result}")
                    except Exception as exc:
                        self.stdout.write(self.style.WARNING(
                            f"  卡片发送失败({exc}),降级为文本消息"
                        ))
                        use_card = False

                # 使用文本消息(降级方案或默认方案)
                if not use_card:
                    self.stdout.write("  使用文本消息发送")
                    # 构建文本消息
                    mention_userids = options.get('mention') or []
                    message = build_payment_report_message(
                        data,
                        period_info,
                        report_type,
                        mention_userids
                    )

                    # 发送文本消息
                    payload = {
                        'msgKey': 'sampleText',
                        'msgParam': json.dumps({'content': message}, ensure_ascii=False),
                        'openConversationId': group_id,
                        'robotCode': dingtalk_app.robot_code,
                    }

                    # 如果需要@用户
                    if mention_userids:
                        payload['atUsers'] = [{'userId': uid} for uid in mention_userids]

                    result = client.post('/v1.0/robot/groupMessages/send', payload)
                    self.stdout.write(f"  文本消息已发送: {result}")

                # 发送文件消息(无论卡片还是文本,都发送Excel附件)
                file_payload = {
                    'msgKey': 'sampleFile',
                    'msgParam': json.dumps({
                        'fileName': excel_filename,
                        'fileType': 'xlsx',
                        'mediaId': media_id,
                    }, ensure_ascii=False),
                    'openConversationId': group_id,
                    'robotCode': dingtalk_app.robot_code,
                }

                file_result = client.post('/v1.0/robot/groupMessages/send', file_payload)
                self.stdout.write(f"  文件消息已发送: {file_result}")

                self.stdout.write(self.style.SUCCESS(f"  ✓ 发送成功"))
                success_count += 1

            except Exception as exc:
                logger.exception(f"处理公司 {company.code} 失败")
                self.stdout.write(self.style.ERROR(f"  ✗ 失败: {exc}"))
                error_count += 1

        # 汇总结果
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(f"完成: {success_count} 成功, {error_count} 失败")
        self.stdout.write("=" * 60)

        if error_count > 0:
            raise CommandError("部分公司处理失败")
