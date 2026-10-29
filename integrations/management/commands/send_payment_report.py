"""发送钉钉付款申请周报/月报。

汇总已同步的付款申请审批实例,生成Excel报表,并推送到钉钉群。
建议定时任务:
- 周报: 每周一早上 09:00 运行 send_payment_report week
- 月报: 每月1日早上 09:00 运行 send_payment_report month
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from core.models import Company
from integrations.models import DingtalkApp, DingtalkProcessConfig, DingtalkGroupConfig
from integrations.services.payment_organizations import (
    PAYMENT_REPORT_COMPANY_APPLICATION_NAMES,
    PAYMENT_REPORT_COMPANY_CODES,
    payment_app_for_company,
)
from integrations.services.dingtalk_client import DingtalkClient
from integrations.services.payment_a2ui import DingtalkA2UIClient, build_payment_a2ui_messages
from integrations.services.payment_excel import generate_payment_excel
from integrations.services.payment_message import build_payment_report_message
from integrations.services.payment_report import (
    analyze_payment_applications,
    get_last_month_range,
    get_last_week_range,
    get_previous_day_range,
)

logger = logging.getLogger("integrations")


class Command(BaseCommand):
    help = "按申请公司发送钉钉付款日报/周报/月报到对应群"

    def add_arguments(self, parser):
        parser.add_argument(
            'report_type',
            choices=['day', 'week', 'month'],
            help="报表类型: day(日报)、week(周报) 或 month(月报)"
        )
        parser.add_argument("--app-id", type=int, help="来源钉钉应用ID，共享应用时用于明确选择")
        parser.add_argument(
            '--company',
            help="公司代码（仅支持 FNS/NBHH）；默认发送已启用的目标公司"
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
            help="报表输出目录,默认为 data/payment_reports（Excel、A2UI JSON 和回执）"
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help="仅生成报表文件（Excel 和 A2UI JSON）,不发送消息"
        )
        parser.add_argument(
            '--mention',
            nargs='+',
            help="要@的用户ID列表(空格分隔)"
        )
        parser.add_argument(
            '--no-card',
            action='store_true',
            help="强制使用文本消息,不使用 A2UI 卡片"
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
        if report_type == 'day':
            period_info = get_previous_day_range(base_date)
            self.stdout.write(f"生成日报: {period_info['label']}")
        elif report_type == 'week':
            period_info = get_last_week_range(base_date)
            self.stdout.write(f"生成周报: {period_info['label']}")
        else:
            period_info = get_last_month_range(base_date)
            self.stdout.write(f"生成月报: {period_info['label']}")

        # 确定要处理的公司
        if options['company']:
            if options['company'] not in PAYMENT_REPORT_COMPANY_CODES:
                allowed = "、".join(
                    f"{code}（{name}）"
                    for code, name in PAYMENT_REPORT_COMPANY_APPLICATION_NAMES.items()
                )
                raise CommandError(f"付款申请报表仅支持以下公司：{allowed}")
            try:
                companies = [Company.objects.get(code=options['company'], is_active=True)]
            except Company.DoesNotExist as exc:
                raise CommandError(f"找不到公司代码: {options['company']}") from exc
        else:
            # 获取所有启用钉钉应用的公司
            companies = Company.objects.filter(
                is_active=True,
                code__in=PAYMENT_REPORT_COMPANY_CODES,
            ).filter(
                Q(dingtalk_app__is_active=True, dingtalk_app__company_mappings__isnull=True)
                | Q(dingtalk_company_mappings__app__is_active=True)
            ).distinct()

        if options.get("app_id") and not options.get("company"):
            companies = companies.filter(Q(dingtalk_app__pk=options["app_id"]) | Q(dingtalk_company_mappings__app_id=options["app_id"])).distinct()

        if not companies:
            self.stdout.write(self.style.WARNING("没有已启用钉钉应用的目标报表公司（FNS/NBHH）"))
            return

        # 准备输出目录
        if options['output_dir']:
            output_dir = Path(options['output_dir'])
            output_dir.mkdir(parents=True, exist_ok=True)
        else:
            output_dir = Path(settings.BASE_DIR) / 'data' / 'payment_reports'
            output_dir.mkdir(parents=True, exist_ok=True)

        success_count = 0
        error_count = 0

        # 逐公司处理
        for company in companies:
            try:
                report_company_name = PAYMENT_REPORT_COMPANY_APPLICATION_NAMES.get(company.code, company.name)
                self.stdout.write(f"\n处理公司: {report_company_name} ({company.code})")

                # 获取钉钉应用
                try:
                    dingtalk_app = payment_app_for_company(company, options.get("app_id"))
                except ValueError as exc:
                    raise CommandError(str(exc)) from exc

                if not dingtalk_app.is_active:
                    raise CommandError("钉钉应用未启用")

                # 获取审批模板
                process_code = options.get('process_code')
                if not process_code:
                    process_configs = list(DingtalkProcessConfig.objects.filter(
                        app=dingtalk_app, is_active=True, name__icontains='付款申请',
                    ))
                    if len(process_configs) != 1:
                        raise CommandError("需明确一个付款申请模板，请用 --process-code 指定")
                    process_code = process_configs[0].process_code

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

                data['company_name'] = report_company_name

                # 生成Excel
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                excel_filename = (
                    f"付款申请{dict(day='日报', week='周报', month='月报')[report_type]}_"
                    f"{company.code}_{timestamp}.xlsx"
                )
                excel_path = output_dir / excel_filename

                self.stdout.write(f"  生成Excel: {excel_path}")
                generate_payment_excel(data, period_info, str(excel_path))

                use_card = not options.get('no_card')
                if use_card:
                    a2ui_messages = build_payment_a2ui_messages(
                        data, period_info, report_company_name, report_type,
                    )
                    a2ui_path = excel_path.with_suffix('.a2ui.json')
                    a2ui_path.write_text(
                        json.dumps(a2ui_messages, ensure_ascii=False, indent=2) + '\n',
                        encoding='utf-8',
                    )
                    self.stdout.write(f"  生成A2UI: {a2ui_path}")

                if options['dry_run']:
                    self.stdout.write(self.style.SUCCESS(
                        f"  ✓ Dry-run模式,报表文件已生成,未发送消息"
                    ))
                    success_count += 1
                    continue

                # 发送到钉钉群；显式群 ID 也必须属于当前公司的多选配置。
                group_id = options.get("group_id")
                targets = list(
                    DingtalkGroupConfig.objects.filter(
                        app=dingtalk_app,
                        is_active=True,
                    )
                    .filter(Q(companies=company) | Q(companies__isnull=True, company=company))
                    .distinct()
                )
                targets = [
                    group
                    for group in targets
                    if report_type in (group.payment_report_types or [])
                ]

                if group_id:
                    configured_targets = targets
                    targets = [
                        group
                        for group in configured_targets
                        if group.open_conversation_id == group_id
                    ]
                    configured_group = DingtalkGroupConfig.objects.filter(
                        app=dingtalk_app, open_conversation_id=group_id,
                    ).exists()
                    if (configured_targets or configured_group) and not targets:
                        raise CommandError(
                            "指定群未在该公司的钉钉群推送配置中勾选，拒绝发送"
                        )
                elif len(targets) == 1:
                    group_id = targets[0].open_conversation_id
                elif len(targets) > 1:
                    raise CommandError(
                        "组织存在多个付款推送群，请用 --group-id 明确目标"
                    )

                if not group_id:
                    raise CommandError(
                        "未指定组织推送群，请配置群或使用 --group-id"
                    )

                # 检查机器人配置
                if not dingtalk_app.robot_code:
                    raise CommandError("未配置机器人Code，请在 Django Admin 中配置 DingtalkApp.robot_code")

                self.stdout.write(f"  发送到钉钉群: {group_id}")

                client = DingtalkClient(dingtalk_app)
                if use_card:
                    a2ui_client = DingtalkA2UIClient(client)
                    a2ui_client.check_available()

                # 上传Excel
                with open(excel_path, 'rb') as f:
                    excel_content = f.read()

                media_id = client.upload_media(excel_filename, excel_content)
                self.stdout.write(f"  Excel已上传, media_id: {media_id}")

                # 默认使用 A2UI；旧 card_template_id 不参与该通道。
                if use_card:
                    self.stdout.write("  使用 A2UI 卡片发送")
                    receipt_path = excel_path.with_suffix('.a2ui.receipt.json')
                    try:
                        card_result = a2ui_client.send_card(group_id, a2ui_messages, receipt_path)
                        self.stdout.write(
                            f"  A2UI 卡片已发送并完结: outTrackId={card_result['outTrackId']}"
                        )
                        self.stdout.write(f"  卡片回执: {receipt_path}")
                    except Exception as exc:
                        raise CommandError(f"A2UI 卡片发送失败：{exc}") from exc

                # 仅显式指定 --no-card 时发送文本消息
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
