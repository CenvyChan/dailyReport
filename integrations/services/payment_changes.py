"""钉钉付款申请变更追踪与报告生成。

跟踪审批实例的状态/金额变化,生成变更报告用于:
1. 每日同步后的变更摘要
2. 周报/月报中的"本期变更"章节
3. 异常提醒(如大额变更、逾期未完成等)
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from integrations.models import DingtalkApprovalInstance

logger = logging.getLogger("integrations")


class ChangeType:
    """变更类型枚举。"""
    STATUS_CHANGED = 'STATUS_CHANGED'
    AMOUNT_CHANGED = 'AMOUNT_CHANGED'
    NEW_CREATED = 'NEW_CREATED'
    FORM_UPDATED = 'FORM_UPDATED'


class ChangeTracker:
    """变更追踪器。

    用法:
        tracker = ChangeTracker()
        tracker.track_status_change(instance, old_status, new_status)
        tracker.track_amount_change(instance, old_amount, new_amount)
        report = tracker.generate_report()
    """

    def __init__(self):
        self.changes = []

    def track_status_change(self, instance, old_status, new_status):
        """记录状态变更。"""
        self.changes.append({
            'type': ChangeType.STATUS_CHANGED,
            'instance_id': instance.process_instance_id,
            'company': instance.company.code,
            'title': instance.title,
            'old_value': old_status,
            'new_value': new_status,
            'timestamp': timezone.now(),
            'amount': instance.amount,
        })

    def track_amount_change(self, instance, old_amount, new_amount):
        """记录金额变更。"""
        diff = new_amount - old_amount if (new_amount and old_amount) else None

        self.changes.append({
            'type': ChangeType.AMOUNT_CHANGED,
            'instance_id': instance.process_instance_id,
            'company': instance.company.code,
            'title': instance.title,
            'old_value': old_amount,
            'new_value': new_amount,
            'diff': diff,
            'timestamp': timezone.now(),
        })

    def track_new_instance(self, instance):
        """记录新增实例。"""
        self.changes.append({
            'type': ChangeType.NEW_CREATED,
            'instance_id': instance.process_instance_id,
            'company': instance.company.code,
            'title': instance.title,
            'amount': instance.amount,
            'status': instance.status,
            'timestamp': timezone.now(),
        })

    def generate_report(self):
        """生成变更报告。

        Returns:
            dict: {
                'summary': {按类型统计},
                'by_company': {按公司分组},
                'important_changes': [重要变更列表],
            }
        """
        if not self.changes:
            return {
                'summary': {},
                'by_company': {},
                'important_changes': [],
            }

        # 按类型统计
        summary = defaultdict(int)
        for change in self.changes:
            summary[change['type']] += 1

        # 按公司分组
        by_company = defaultdict(list)
        for change in self.changes:
            by_company[change['company']].append(change)

        # 识别重要变更
        important_changes = []

        for change in self.changes:
            # 1. 大额金额变更(>10000元)
            if change['type'] == ChangeType.AMOUNT_CHANGED:
                diff = change.get('diff')
                if diff and abs(diff) > 10000:
                    important_changes.append({
                        **change,
                        'reason': f"大额变更(差额 ¥{diff:,.2f})"
                    })

            # 2. 状态变更为已终止
            if change['type'] == ChangeType.STATUS_CHANGED:
                if change['new_value'] == 'TERMINATED':
                    important_changes.append({
                        **change,
                        'reason': '审批已终止'
                    })

            # 3. 新增大额申请(>50000元)
            if change['type'] == ChangeType.NEW_CREATED:
                amount = change.get('amount')
                if amount and amount > 50000:
                    important_changes.append({
                        **change,
                        'reason': f"新增大额申请(¥{amount:,.2f})"
                    })

        return {
            'summary': dict(summary),
            'by_company': dict(by_company),
            'important_changes': important_changes,
        }


def detect_changes_since(company, since_time, process_code=None):
    """检测指定时间后的变更。

    Args:
        company: Company实例
        since_time: 起始时间
        process_code: 审批模板Code(可选)

    Returns:
        ChangeTracker: 包含所有变更的追踪器
    """
    tracker = ChangeTracker()

    # 查询条件
    filters = {
        'company': company,
        'updated_at__gte': since_time,
    }
    if process_code:
        filters['process_code'] = process_code

    # 查询最近更新的实例
    recent_instances = DingtalkApprovalInstance.objects.filter(**filters)

    for instance in recent_instances:
        # 判断是否为新建(created_at ≈ updated_at)
        time_diff = (instance.updated_at - instance.created_at).total_seconds()
        if time_diff < 60:  # 1分钟内视为新建
            tracker.track_new_instance(instance)
        else:
            # TODO: 实际项目中应该有历史记录表来追踪变更
            # 这里简化处理,只标记为可能有更新
            pass

    return tracker


def generate_change_summary(company, start_date, end_date, process_code=None):
    """生成指定期间的变更摘要。

    Args:
        company: Company实例
        start_date: 开始日期
        end_date: 结束日期
        process_code: 审批模板Code(可选)

    Returns:
        dict: 变更摘要数据
    """
    # 查询条件
    filters = {
        'company': company,
        'create_time__gte': datetime.combine(start_date, datetime.min.time()),
        'create_time__lte': datetime.combine(end_date, datetime.max.time()),
    }
    if process_code:
        filters['process_code'] = process_code

    instances = DingtalkApprovalInstance.objects.filter(**filters)

    # 按状态分类
    by_status = defaultdict(int)
    by_status_amount = defaultdict(Decimal)

    for instance in instances:
        by_status[instance.status] += 1
        if instance.amount:
            by_status_amount[instance.status] += instance.amount

    # 查找本期完成的审批
    completed_in_period = instances.filter(
        status='COMPLETED',
        finish_time__gte=datetime.combine(start_date, datetime.min.time()),
        finish_time__lte=datetime.combine(end_date, datetime.max.time()),
    )

    # 查找本期终止的审批
    terminated_in_period = instances.filter(
        status='TERMINATED',
        finish_time__gte=datetime.combine(start_date, datetime.min.time()),
        finish_time__lte=datetime.combine(end_date, datetime.max.time()),
    )

    # 查找逾期未完成的审批(创建超过7天仍在进行中)
    overdue_threshold = timezone.now() - timedelta(days=7)
    overdue_instances = instances.filter(
        status='RUNNING',
        create_time__lt=overdue_threshold,
    )

    return {
        'total_count': instances.count(),
        'by_status': dict(by_status),
        'by_status_amount': {k: float(v) for k, v in by_status_amount.items()},
        'completed_in_period': completed_in_period.count(),
        'terminated_in_period': terminated_in_period.count(),
        'overdue_count': overdue_instances.count(),
        'overdue_details': [
            {
                'id': inst.process_instance_id,
                'title': inst.title,
                'amount': float(inst.amount) if inst.amount else 0,
                'create_date': inst.create_time.strftime('%Y-%m-%d'),
                'days_elapsed': (timezone.now() - inst.create_time).days,
            }
            for inst in overdue_instances[:10]  # 最多返回10条
        ],
    }


def format_change_message(changes_report):
    """将变更报告格式化为可读消息。

    Args:
        changes_report: generate_report()的返回值

    Returns:
        str: 格式化的Markdown消息
    """
    lines = ["📋 付款申请同步变更报告", "━━━━━━━━━━━━━━━━━━", ""]

    summary = changes_report['summary']
    if not summary:
        lines.append("✨ 无变更")
        return '\n'.join(lines)

    # 汇总统计
    lines.append("📊 变更统计:")
    if ChangeType.NEW_CREATED in summary:
        lines.append(f"  🆕 新增: {summary[ChangeType.NEW_CREATED]}条")
    if ChangeType.STATUS_CHANGED in summary:
        lines.append(f"  🔄 状态变更: {summary[ChangeType.STATUS_CHANGED]}条")
    if ChangeType.AMOUNT_CHANGED in summary:
        lines.append(f"  💰 金额变更: {summary[ChangeType.AMOUNT_CHANGED]}条")
    lines.append("")

    # 重要变更
    important = changes_report['important_changes']
    if important:
        lines.append("⚠️ 重要变更:")
        for idx, change in enumerate(important[:5], 1):  # 最多显示5条
            lines.append(f"  {idx}. {change['title']}")
            lines.append(f"     {change['reason']}")
        if len(important) > 5:
            lines.append(f"  ...还有{len(important)-5}条重要变更")
        lines.append("")

    return '\n'.join(lines)
