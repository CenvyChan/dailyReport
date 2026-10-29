"""钉钉付款申请同步命令。

功能特性:
1. 时间范围:默认同步上个月的完整月份数据
2. 状态跟踪:记录审批状态变更(RUNNING→COMPLETED等)
3. 金额校正:记录金额变化(审批可能被修改)
4. 变更通知:生成变更报告供报表使用
5. 幂等性:支持多次运行,只更新变化的数据
"""

import logging
from datetime import datetime, timedelta, timezone as dt_timezone

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
            '--full-sync',
            action='store_true',
            help="全量同步:从2024年1月1日至今的所有数据(首次部署时使用)"
        )
        parser.add_argument(
            '--current-month',
            action='store_true',
            help="同步当前月份:从本月1号至今(用于手动触发当月报表)"
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

            # 计算时间范围
            today = timezone.now().date()
            now = timezone.now()

            if options.get('full_sync'):
                # 全量同步:从2024-01-01至今
                start_time = timezone.make_aware(
                    timezone.datetime(2024, 1, 1, 0, 0, 0)
                )
                end_time = now
                time_desc = "全量同步(2024-01-01至今)"

            elif options.get('current_month'):
                # 当月同步:从本月1号至今
                first_day_of_current_month = today.replace(day=1)
                start_time = timezone.make_aware(
                    timezone.datetime.combine(first_day_of_current_month, timezone.datetime.min.time())
                )
                end_time = now
                time_desc = "当月数据(本月1号至今)"

            else:
                # 默认:上个月的完整月份
                first_day_of_current_month = today.replace(day=1)
                last_day_of_last_month = first_day_of_current_month - timedelta(days=1)
                first_day_of_last_month = last_day_of_last_month.replace(day=1)

                start_time = timezone.make_aware(
                    timezone.datetime.combine(first_day_of_last_month, timezone.datetime.min.time())
                )
                end_time = timezone.make_aware(
                    timezone.datetime.combine(last_day_of_last_month, timezone.datetime.max.time())
                )
                time_desc = "上个月完整月份"

            start_ms = int(start_time.timestamp() * 1000)
            end_ms = int(end_time.timestamp() * 1000)

            self.stdout.write(
                f"  时间范围: {start_time.strftime('%Y-%m-%d')} "
                f"至 {end_time.strftime('%Y-%m-%d')} ({time_desc})"
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
        from integrations.services.payment_organizations import approval_scope, instance_defaults, save_approval

        counts = dict(created=0, updated=0, status_changed=0, amount_changed=0)
        for instance_id in instance_ids:
            raw = client.get_instance(instance_id)
            if dry_run:
                instance_defaults(config.app, config, raw, instance_id)
                exists = approval_scope(config.app, config.process_code).filter(process_instance_id=instance_id).exists()
                counts["updated" if exists else "created"] += 1
                continue
            row, created, previous = save_approval(config.app, config, raw, instance_id)
            counts["created" if created else "updated"] += 1
            if track_changes and not created:
                counts["status_changed"] += previous["status"] != row.status
                counts["amount_changed"] += previous["amount"] != row.amount
        return counts

    def _extract_instance_data(self, company, config, instance_data, instance_id=None):
        from integrations.services.payment_organizations import instance_defaults
        return instance_defaults(config.app, config, instance_data, instance_id or instance_data.get("process_instance_id"))
