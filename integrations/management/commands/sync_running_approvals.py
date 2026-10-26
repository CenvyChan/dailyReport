"""同步未完结的付款审批命令。

用于定时或手动触发，仅同步RUNNING状态的审批实例。
适合频繁轮询场景，避免重复拉取已完结的历史数据。
"""

import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Company
from integrations.models import DingtalkApprovalInstance, DingtalkProcessConfig
from integrations.services.dingtalk_client import DingtalkClient

logger = logging.getLogger("integrations")


class Command(BaseCommand):
    help = "仅同步RUNNING状态的付款审批(用于机器人命令或频繁轮询)"

    def add_arguments(self, parser):
        parser.add_argument(
            '--company',
            help="仅同步指定公司代码,缺省同步全部"
        )
        parser.add_argument(
            '--lookback-hours',
            type=int,
            default=72,
            help="回看小时数,默认72小时(3天),避免遗漏刚创建的审批"
        )

    def handle(self, *args, **options):
        # 筛选公司
        companies_qs = Company.objects.filter(is_active=True)
        if options.get('company'):
            companies_qs = companies_qs.filter(code=options['company'])

        for company in companies_qs:
            self.stdout.write(f"\n{'='*60}")
            self.stdout.write(f"同步公司: {company.name} ({company.code})")
            self.stdout.write(f"{'='*60}")

            try:
                result = self._sync_company(company, options)
                self.stdout.write(self.style.SUCCESS(
                    f"✓ 新增: {result['created']}, "
                    f"更新: {result['updated']}, "
                    f"状态变更: {result['status_changed']}"
                ))
            except Exception as exc:
                logger.exception(f"同步公司 {company.code} 失败")
                self.stdout.write(self.style.ERROR(f"✗ 异常: {exc}"))

    def _sync_company(self, company, options):
        """同步单个公司的未完结审批。"""
        try:
            app = company.dingtalk_app
        except Exception as exc:
            raise Exception(f'获取钉钉应用失败: {exc}')

        if not app.is_active:
            raise Exception('钉钉应用未启用')

        # 获取所有付款申请模板
        process_configs = DingtalkProcessConfig.objects.filter(
            app=app,
            is_active=True,
            name__icontains='付款申请',
        )

        if not process_configs.exists():
            raise Exception('未配置付款申请审批模板')

        client = DingtalkClient(app)
        total_created = 0
        total_updated = 0
        total_status_changed = 0

        # 计算时间范围：往前推N小时
        lookback_hours = options.get('lookback_hours', 72)
        end_time = timezone.now()
        start_time = end_time - timedelta(hours=lookback_hours)
        start_ms = int(start_time.timestamp() * 1000)
        end_ms = int(end_time.timestamp() * 1000)

        self.stdout.write(
            f"  时间范围: 最近{lookback_hours}小时 "
            f"({start_time.strftime('%Y-%m-%d %H:%M')} 至 "
            f"{end_time.strftime('%Y-%m-%d %H:%M')})"
        )

        for config in process_configs:
            self.stdout.write(f"\n  模板: {config.name}")

            # 1. 获取实例ID列表
            instance_ids = client.list_instance_ids(
                config.process_code,
                start_ms,
                end_ms,
            )
            self.stdout.write(f"    获取到 {len(instance_ids)} 个实例")

            # 2. 过滤：只处理RUNNING或本地不存在的
            need_sync = []
            for iid in instance_ids:
                try:
                    inst = DingtalkApprovalInstance.objects.get(
                        company=company,
                        process_instance_id=iid
                    )
                    if inst.status == 'RUNNING':
                        need_sync.append(iid)
                except DingtalkApprovalInstance.DoesNotExist:
                    need_sync.append(iid)

            self.stdout.write(f"    需同步 {len(need_sync)} 个(RUNNING或新增)")

            # 3. 逐个同步
            for iid in need_sync:
                try:
                    detail = client.get_instance(iid)
                    created, updated, status_changed, _ = self._save_instance(
                        company, config, iid, detail
                    )
                    total_created += created
                    total_updated += updated
                    total_status_changed += status_changed
                except Exception as exc:
                    logger.warning(f"处理审批实例 {iid} 失败: {exc}")

        return {
            'created': total_created,
            'updated': total_updated,
            'status_changed': total_status_changed,
        }

    def _save_instance(self, company, config, instance_id, detail):
        """保存或更新单个审批实例,返回(created, updated, status_changed, amount_changed)。"""
        data = self._extract_fields(instance_id, detail)
        try:
            inst = DingtalkApprovalInstance.objects.get(
                company=company,
                process_instance_id=instance_id
            )
            created = False
            updated = True
            status_changed = (inst.status != data['status'])
            amount_changed = (inst.payment_amount_cny != data.get('payment_amount_cny'))

            for k, v in data.items():
                setattr(inst, k, v)
            inst.save()

        except DingtalkApprovalInstance.DoesNotExist:
            data['company'] = company
            data['process_config'] = config
            DingtalkApprovalInstance.objects.create(**data)
            created = True
            updated = False
            status_changed = False
            amount_changed = False

        return created, updated, status_changed, amount_changed

    def _extract_fields(self, instance_id, instance_data):
        """从钉钉API返回的实例数据中提取字段。"""
        form_values = {
            item['name']: item['value']
            for item in instance_data.get('form_component_values', [])
        }

        def get_decimal(key, default='0'):
            val = form_values.get(key, default)
            if isinstance(val, (int, float)):
                return val
            if isinstance(val, str):
                return val.replace(',', '').strip() or default
            return default

        return {
            'process_instance_id': instance_data.get('process_instance_id', instance_id),
            'title': instance_data.get('title', ''),
            'originator_name': instance_data.get('originator_user_id', {}).get('name', ''),
            'originator_userid': instance_data.get('originator_user_id', {}).get('user_id', ''),
            'status': instance_data.get('status', 'UNKNOWN'),
            'result': instance_data.get('result', 'NONE'),
            'create_time': timezone.datetime.fromtimestamp(
                instance_data.get('create_time', 0) / 1000, tz=timezone.get_current_timezone()
            ),
            'finish_time': (
                timezone.datetime.fromtimestamp(
                    instance_data.get('finish_time', 0) / 1000, tz=timezone.get_current_timezone()
                )
                if instance_data.get('finish_time')
                else None
            ),
            'payment_amount_cny': get_decimal('金额（元）'),
            'payment_note': form_values.get('备注', ''),
            'raw_data': instance_data,
        }
