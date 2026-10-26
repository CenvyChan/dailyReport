"""钉钉付款申请报表服务单元测试。"""

from datetime import datetime, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.models import Company
from integrations.models import DingtalkApp, DingtalkApprovalInstance, DingtalkProcessConfig
from integrations.services.payment_report import (
    analyze_payment_applications,
    get_last_month_range,
    get_last_week_range,
)


class PaymentReportTest(TestCase):
    """测试付款申请报表生成功能。"""

    def setUp(self):
        """创建测试数据。"""
        # 创建公司
        self.company = Company.objects.create(
            code='TEST',
            name='测试公司',
        )

        # 创建钉钉应用
        self.dingtalk_app = DingtalkApp.objects.create(
            company=self.company,
            name='测试应用',
            app_key='test_key',
            app_secret='test_secret',
            corp_id='test_corp_id',
            agent_id='test_agent',
        )

        # 创建审批模板配置
        self.process_config = DingtalkProcessConfig.objects.create(
            app=self.dingtalk_app,
            process_code='TEST_PAYMENT',
            name='付款申请',
            amount_component='付款总额',
        )

    def test_get_last_week_range(self):
        """测试获取上周时间范围。"""
        # 假设今天是2026-10-26(周一)
        base_date = datetime(2026, 10, 26).date()
        period = get_last_week_range(base_date)

        # 上周一应该是10-19
        self.assertEqual(period['start_date'].day, 19)
        # 上周日应该是10-25
        self.assertEqual(period['end_date'].day, 25)
        # 标签应该包含周数
        self.assertIn('2026年', period['label'])

    def test_get_last_month_range(self):
        """测试获取上月时间范围。"""
        # 假设今天是2026-10-26
        base_date = datetime(2026, 10, 26).date()
        period = get_last_month_range(base_date)

        # 上月应该是9月
        self.assertEqual(period['start_date'].month, 9)
        self.assertEqual(period['start_date'].day, 1)
        # 9月有30天
        self.assertEqual(period['end_date'].day, 30)
        # 标签
        self.assertEqual(period['label'], '2026年9月')

    def test_analyze_empty_data(self):
        """测试空数据情况。"""
        now = timezone.now()
        start = now - timedelta(days=7)

        result = analyze_payment_applications(
            self.company,
            start,
            now,
            self.process_config.process_code
        )

        self.assertEqual(result['summary']['total_count'], 0)
        self.assertEqual(result['summary']['total_amount'], Decimal('0'))
        self.assertEqual(len(result['by_recipient']), 0)

    def test_analyze_with_data(self):
        """测试有数据的情况。"""
        # 创建测试审批实例
        now = timezone.now()

        # 审批1: 收款人A, 100元, 已完成
        DingtalkApprovalInstance.objects.create(
            company=self.company,
            process_code=self.process_config.process_code,
            process_instance_id='test_001',
            title='付款申请-供应商A',
            status='COMPLETED',
            amount=Decimal('100.00'),
            create_time=now - timedelta(days=2),
            form_values=[
                {'name': '收款人全称', 'value': '供应商A'},
                {'name': '付款事由', 'value': '采购款'},
            ],
        )

        # 审批2: 收款人A, 50元, 进行中
        DingtalkApprovalInstance.objects.create(
            company=self.company,
            process_code=self.process_config.process_code,
            process_instance_id='test_002',
            title='付款申请-供应商A',
            status='RUNNING',
            amount=Decimal('50.00'),
            create_time=now - timedelta(days=1),
            form_values=[
                {'name': '收款人全称', 'value': '供应商A'},
                {'name': '付款事由', 'value': '服务费'},
            ],
        )

        # 审批3: 收款人B, 200元, 已完成
        DingtalkApprovalInstance.objects.create(
            company=self.company,
            process_code=self.process_config.process_code,
            process_instance_id='test_003',
            title='付款申请-供应商B',
            status='COMPLETED',
            amount=Decimal('200.00'),
            create_time=now - timedelta(days=3),
            form_values=[
                {'name': '收款人', 'value': '供应商B'},  # 测试字段名兼容
                {'name': '付款事由', 'value': '设备款'},
            ],
        )

        # 执行分析
        start = now - timedelta(days=7)
        result = analyze_payment_applications(
            self.company,
            start,
            now,
            self.process_config.process_code
        )

        # 验证汇总
        self.assertEqual(result['summary']['total_count'], 3)
        self.assertEqual(result['summary']['total_amount'], Decimal('350.00'))
        self.assertEqual(result['summary']['by_status']['COMPLETED'], 2)
        self.assertEqual(result['summary']['by_status']['RUNNING'], 1)

        # 验证按收款人分组
        self.assertEqual(len(result['by_recipient']), 2)

        # 收款人应该按金额倒序(B:200, A:150)
        recipient_b = result['by_recipient'][0]
        self.assertEqual(recipient_b['recipient'], '供应商B')
        self.assertEqual(recipient_b['amount'], Decimal('200.00'))
        self.assertEqual(recipient_b['count'], 1)

        recipient_a = result['by_recipient'][1]
        self.assertEqual(recipient_a['recipient'], '供应商A')
        self.assertEqual(recipient_a['amount'], Decimal('150.00'))
        self.assertEqual(recipient_a['count'], 2)

        # 验证明细
        self.assertEqual(len(recipient_a['details']), 2)
        detail = recipient_a['details'][0]
        self.assertIn('create_date', detail)
        self.assertIn('amount', detail)
        self.assertIn('reason', detail)
        self.assertIn('status', detail)

    def test_analyze_unknown_recipient(self):
        """测试未知收款人的处理。"""
        now = timezone.now()

        # 创建没有收款人字段的审批
        DingtalkApprovalInstance.objects.create(
            company=self.company,
            process_code=self.process_config.process_code,
            process_instance_id='test_004',
            title='付款申请-测试',
            status='RUNNING',
            amount=Decimal('88.88'),
            create_time=now,
            form_values=[
                {'name': '其他字段', 'value': '其他值'},
            ],
        )

        start = now - timedelta(hours=1)
        result = analyze_payment_applications(
            self.company,
            start,
            now + timedelta(hours=1),
            self.process_config.process_code
        )

        # 应该归类为"未知收款人"
        self.assertEqual(len(result['by_recipient']), 1)
        self.assertEqual(result['by_recipient'][0]['recipient'], '未知收款人')

    def test_analyze_different_process_code(self):
        """测试不同审批模板的隔离。"""
        now = timezone.now()

        # 创建付款申请
        DingtalkApprovalInstance.objects.create(
            company=self.company,
            process_code=self.process_config.process_code,
            process_instance_id='test_005',
            amount=Decimal('100.00'),
            create_time=now,
        )

        # 创建其他类型审批
        DingtalkApprovalInstance.objects.create(
            company=self.company,
            process_code='OTHER_PROCESS',
            process_instance_id='test_006',
            amount=Decimal('999.99'),
            create_time=now,
        )

        start = now - timedelta(hours=1)
        result = analyze_payment_applications(
            self.company,
            start,
            now + timedelta(hours=1),
            self.process_config.process_code
        )

        # 应该只统计付款申请,不包含其他审批
        self.assertEqual(result['summary']['total_count'], 1)
        self.assertEqual(result['summary']['total_amount'], Decimal('100.00'))
