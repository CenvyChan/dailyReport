"""钉钉付款申请同步命令。

功能特性:
1. 时间范围:默认同步上个月的完整月份数据
2. 状态跟踪:记录审批状态变更(RUNNING→COMPLETED等)
3. 金额校正:记录金额变化(审批可能被修改)
4. 变更通知:生成变更报告供报表使用
5. 幂等性:支持多次运行,只更新变化的数据
"""

import logging
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import Company
from integrations.models import DingtalkApprovalInstance, DingtalkProcessConfig, SyncRun
from integrations.services.dingtalk_client import DingtalkClient

logger = logging.getLogger("integrations")


class Command(BaseCommand):
    help = "同步钉钉付款申请审批实例(默认同步上个月数据),支持增量更新和变更追踪"

    def add_arguments(self, parser):
        parser.add_argument(
            '--company',
            help="仅同步指定公司代码,缺省同步全部"
        )
        parser.add_argument(
            '--process-code',
            help="指定审批模板Code,缺省同步所有启用的模板"
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help="强制重新同步,忽略当天已同步判断"
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help="仅统计不写库"
        )
        parser.add_argument(
            '--track-changes',
            action='store_true',
            default=True,
            help="记录数据变更(默认开启)"
        )

    def handle(self, *args, **options):
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

        # 执行同步
        total_success = 0
        total_error = 0

        for company in companies:
            try:
                self.stdout.write(f"\n{'='*60}")
                self.stdout.write(f"同步公司: {company.name} ({company.code})")
                self.stdout.write(f"{'='*60}")

                result = self._sync_company(company, options)

                if result['error']:
                    self.stdout.write(self.style.ERROR(f"✗ {result['error']}"))
                    total_error += 1
                else:
                    self.stdout.write(self.style.SUCCESS(
                        f"✓ 新增:{result['created']} 更新:{result['updated']} "
                        f"状态变更:{result['status_changed']} "
                        f"金额变更:{result['amount_changed']}"
                    ))
                    total_success += 1

            except Exception as exc:
                logger.exception(f"同步公司 {company.code} 失败")
                self.stdout.write(self.style.ERROR(f"✗ 异常: {exc}"))
                total_error += 1

        # 汇总
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"完成: {total_success} 成功, {total_error} 失败")
        self.stdout.write(f"{'='*60}")

        if total_error > 0:
            raise CommandError("部分公司同步失败")

    def _sync_company(self, company, options):
        """同步单个公司的付款申请。"""
        try:
            app = company.dingtalk_app
        except Exception as exc:
            return {'error': f'获取钉钉应用失败: {exc}'}

        if not app.is_active:
            return {'error': '钉钉应用未启用'}

        # 获取要同步的审批模板
        if options.get('process_code'):
            process_configs = DingtalkProcessConfig.objects.filter(
                app=app,
                process_code=options['process_code'],
                is_active=True,
            )
        else:
            # 同步所有付款申请模板
            process_configs = DingtalkProcessConfig.objects.filter(
                app=app,
                is_active=True,
                name__icontains='付款申请',
            )

        if not process_configs.exists():
            return {'error': '未配置付款申请审批模板'}

        # 构造钉钉客户端
        client = DingtalkClient(app)

        # 统计变量
        total_created = 0
        total_updated = 0
        total_status_changed = 0
        total_amount_changed = 0

        # 遍历模板
        for config in process_configs:
            self.stdout.write(f"\n处理模板: {config.name} ({config.process_code})")

            # 计算时间范围：上个月的完整月份
            today = timezone.now().date()
            # 上个月的第一天
            first_day_of_current_month = today.replace(day=1)
            last_day_of_last_month = first_day_of_current_month - timedelta(days=1)
            first_day_of_last_month = last_day_of_last_month.replace(day=1)

            # 转为datetime并设置时区
            start_time = timezone.make_aware(
                timezone.datetime.combine(first_day_of_last_month, timezone.datetime.min.time())
            )
            end_time = timezone.make_aware(
                timezone.datetime.combine(last_day_of_last_month, timezone.datetime.max.time())
            )

            start_ms = int(start_time.timestamp() * 1000)
            end_ms = int(end_time.timestamp() * 1000)

            self.stdout.write(
                f"  时间范围: {start_time.strftime('%Y-%m-%d')} "
                f"至 {end_time.strftime('%Y-%m-%d')} (上个月完整月份)"
            )

            try:
                # 1. 获取审批实例ID列表
                self.stdout.write("  获取审批实例ID列表...")
                instance_ids = client.list_instance_ids(
                    config.process_code,
                    start_ms,
                    end_ms,
                )
                self.stdout.write(f"  找到 {len(instance_ids)} 个审批实例")

                if not instance_ids:
                    continue

                # 2. 批量获取详情并更新
                changes = self._sync_instances(
                    company,
                    config,
                    client,
                    instance_ids,
                    options.get('dry_run', False),
                    options.get('track_changes', True),
                )

                total_created += changes['created']
                total_updated += changes['updated']
                total_status_changed += changes['status_changed']
                total_amount_changed += changes['amount_changed']

            except Exception as exc:
                logger.exception(f"同步模板 {config.process_code} 失败")
                return {'error': f'模板 {config.name} 同步失败: {exc}'}

        return {
            'error': None,
            'created': total_created,
            'updated': total_updated,
            'status_changed': total_status_changed,
            'amount_changed': total_amount_changed,
        }

    def _sync_instances(self, company, config, client, instance_ids, dry_run, track_changes):
        """同步审批实例列表。"""
        created = 0
        updated = 0
        status_changed = 0
        amount_changed = 0

        for idx, instance_id in enumerate(instance_ids, 1):
            if idx % 10 == 0:
                self.stdout.write(f"  进度: {idx}/{len(instance_ids)}")

            try:
                # 获取详情
                instance_data = client.get_instance(instance_id)

                # 提取字段（传入instance_id以补充可能缺失的字段）
                extracted = self._extract_instance_data(company, config, instance_data, instance_id)

                if dry_run:
                    # Dry-run模式,只统计
                    if DingtalkApprovalInstance.objects.filter(
                        company=company,
                        process_instance_id=instance_id,
                    ).exists():
                        updated += 1
                    else:
                        created += 1
                    continue

                # 查找已存在的实例
                existing = DingtalkApprovalInstance.objects.filter(
                    company=company,
                    process_instance_id=instance_id,
                ).first()

                if existing:
                    # 检查变更
                    has_changes = False
                    changed_fields = []

                    if existing.status != extracted['status']:
                        changed_fields.append(
                            f"状态:{existing.status}→{extracted['status']}"
                        )
                        status_changed += 1
                        has_changes = True

                    if existing.amount != extracted['amount']:
                        changed_fields.append(
                            f"金额:{existing.amount}→{extracted['amount']}"
                        )
                        amount_changed += 1
                        has_changes = True

                    if has_changes:
                        # 更新记录
                        for key, value in extracted.items():
                            setattr(existing, key, value)
                        existing.save()

                        if track_changes and changed_fields:
                            logger.info(
                                f"审批实例 {instance_id} 变更: {', '.join(changed_fields)}"
                            )

                        updated += 1
                else:
                    # 新建记录
                    DingtalkApprovalInstance.objects.create(**extracted)
                    created += 1

            except Exception as exc:
                logger.warning(f"处理审批实例 {instance_id} 失败: {exc}")
                continue

        return {
            'created': created,
            'updated': updated,
            'status_changed': status_changed,
            'amount_changed': amount_changed,
        }

    def _extract_instance_data(self, company, config, instance_data, instance_id):
        """从钉钉API响应提取字段。"""
        from decimal import Decimal

        # 基本信息
        result = {
            'company': company,
            'process_code': config.process_code,
            'process_name': instance_data.get('title', ''),
            'process_instance_id': instance_data.get('process_instance_id') or instance_id,  # 优先从数据取，否则用传入的ID
            'title': instance_data.get('title', ''),
            'status': instance_data.get('status', ''),
            'result': instance_data.get('result', ''),
        }

        # 时间字段
        create_time = instance_data.get('create_time')
        if create_time:
            result['create_time'] = timezone.datetime.fromtimestamp(
                int(create_time) / 1000, tz=timezone.utc
            )

        finish_time = instance_data.get('finish_time')
        if finish_time:
            result['finish_time'] = timezone.datetime.fromtimestamp(
                int(finish_time) / 1000, tz=timezone.utc
            )

        # 发起人信息
        originator = instance_data.get('originator_userid', '')
        result['originator_userid'] = originator
        result['originator_name'] = instance_data.get('originator_name', '')
        result['dept_name'] = instance_data.get('dept_name', '')

        # 表单值
        form_values = instance_data.get('form_component_values', []) or []
        result['form_values'] = form_values

        # 提取金额
        amount = None
        if config.amount_component and form_values:
            for item in form_values:
                if item.get('name') == config.amount_component:
                    try:
                        amount = Decimal(str(item.get('value', 0)))
                    except (ValueError, TypeError):
                        amount = None
                    break

        result['amount'] = amount
        result['raw'] = instance_data

        return result
