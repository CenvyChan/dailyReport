"""钉钉付款申请汇总与报表生成。

按周或月汇总已同步的付款申请审批实例,生成结构化数据供Excel和钉钉消息使用。
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce

from integrations.models import DingtalkApprovalInstance

logger = logging.getLogger("integrations")


def get_last_week_range(base_date=None):
    """获取上周的日期范围(周一到周日)。

    Args:
        base_date: 基准日期,默认今天

    Returns:
        dict: {
            'start': datetime,  # 上周一 00:00:00
            'end': datetime,    # 上周日 23:59:59
            'label': str        # 如"2026年第43周"
        }
    """
    if base_date is None:
        base_date = timezone.localdate() if settings.USE_TZ else datetime.now().date()

    # 获取当前是周几(0=周一, 6=周日)
    weekday = base_date.weekday()

    # 上周一
    last_monday = base_date - timedelta(days=weekday + 7)
    # 上周日
    last_sunday = last_monday + timedelta(days=6)

    start = datetime.combine(last_monday, datetime.min.time())
    end = datetime.combine(last_sunday, datetime.max.time())
    if settings.USE_TZ:
        tz = timezone.get_current_timezone()
        start = timezone.make_aware(start, tz)
        end = timezone.make_aware(end, tz)

    # 获取周数
    week_num = last_monday.isocalendar()[1]
    label = f"{last_monday.year}年第{week_num}周"

    return {
        'start': start,
        'end': end,
        'label': label,
        'start_date': last_monday,
        'end_date': last_sunday,
    }


def get_last_month_range(base_date=None):
    """获取上月的日期范围(1号到月末)。

    Args:
        base_date: 基准日期,默认今天

    Returns:
        dict: {
            'start': datetime,  # 上月1号 00:00:00
            'end': datetime,    # 上月最后一天 23:59:59
            'label': str        # 如"2026年10月"
        }
    """
    if base_date is None:
        base_date = timezone.localdate() if settings.USE_TZ else datetime.now().date()

    # 上月第一天
    if base_date.month == 1:
        first_day = base_date.replace(year=base_date.year - 1, month=12, day=1)
    else:
        first_day = base_date.replace(month=base_date.month - 1, day=1)

    # 上月最后一天
    if first_day.month == 12:
        next_month = first_day.replace(year=first_day.year + 1, month=1, day=1)
    else:
        next_month = first_day.replace(month=first_day.month + 1, day=1)
    last_day = next_month - timedelta(days=1)

    start = datetime.combine(first_day, datetime.min.time())
    end = datetime.combine(last_day, datetime.max.time())
    if settings.USE_TZ:
        tz = timezone.get_current_timezone()
        start = timezone.make_aware(start, tz)
        end = timezone.make_aware(end, tz)

    label = f"{first_day.year}年{first_day.month}月"

    return {
        'start': start,
        'end': end,
        'label': label,
        'start_date': first_day,
        'end_date': last_day,
    }


def _extract_form_value(form_values, *keys):
    """从表单值字典中提取字段值。

    兼容同步历史中的字段字典及 name/value 组件数组。
    按优先级尝试多个可能的字段名。
    """
    if isinstance(form_values, dict):
        return next((form_values[key] for key in keys if form_values.get(key) not in (None, "")), None)
    if not form_values or not isinstance(form_values, list):
        return None

    for item in form_values:
        if not isinstance(item, dict):
            continue
        name = item.get('name', '')
        if name in keys:
            return item.get('value')
    return None


def analyze_payment_applications(company, start_time, end_time, process_code):
    """按收款人汇总付款申请。

    Args:
        company: Company实例
        start_time: 开始时间(datetime)
        end_time: 结束时间(datetime)
        process_code: 审批模板Code

    Returns:
        dict: {
            'summary': {总览统计},
            'by_recipient': [{收款人汇总}],
        }
    """
    # 查询审批实例
    queryset = DingtalkApprovalInstance.objects.filter(
        company=company,
        process_code=process_code,
        create_time__gte=start_time,
        create_time__lte=end_time,
    ).order_by('create_time')

    total_count = queryset.count()
    if total_count == 0:
        return {
            'summary': {
                'total_count': 0,
                'total_amount': Decimal('0'),
                'by_status': {'COMPLETED': 0, 'RUNNING': 0, 'TERMINATED': 0, 'NEW': 0},
            },
            'by_recipient': [],
        }

    # 按状态统计
    status_stats = queryset.aggregate(
        completed=Count('id', filter=Q(status='COMPLETED')),
        running=Count('id', filter=Q(status='RUNNING')),
        terminated=Count('id', filter=Q(status='TERMINATED')),
        new=Count('id', filter=Q(status='NEW')),
        total_amount=Coalesce(Sum('amount'), Decimal('0')),
    )

    # 按收款人分组
    recipients = {}
    from integrations.services.payment_organizations import (
        PAYMENT_REPORT_COMPANY_APPLICATION_NAMES,
        application_company_name,
        payment_app_for_company,
        resolve_company,
    )
    try:
        source_app = payment_app_for_company(company)
    except ValueError:
        source_app = None
    requires_company = bool(source_app and source_app.company_mappings.exists())
    for instance in queryset.select_related('company'):
        form_company = application_company_name(instance.form_values)
        expected_company = PAYMENT_REPORT_COMPANY_APPLICATION_NAMES.get(company.code)
        if expected_company and form_company != expected_company:
            raise ValueError(
                f"审批申请公司「{form_company or '未填写'}」不在付款报表范围，"
                f"项目组织 {company.code} 仅接收「{expected_company}」"
            )
        if requires_company or form_company:
            app = source_app or payment_app_for_company(company)
            if resolve_company(app, instance.form_values).pk != company.pk:
                raise ValueError("审批申请公司与项目组织不一致，请先运行 reconcile_payment_organizations")
        # 从表单值提取收款人(尝试多个可能的字段名)
        recipient = _extract_form_value(
            instance.form_values,
            '收款人全称', '收款人', '收款方', '收款单位', '供应商'
        ) or '未知收款人'

        # 从表单值提取其他字段
        payment_reason = _extract_form_value(
            instance.form_values,
            '付款事由', '事由', '用途', '备注'
        ) or ''

        expected_date = _extract_form_value(
            instance.form_values,
            '期望付款日期', '期望日期', '计划付款日期'
        ) or ''

        # 初始化收款人分组
        if recipient not in recipients:
            recipients[recipient] = {
                'recipient': recipient,
                'count': 0,
                'amount': Decimal('0'),
                'details': [],
            }

        # 累加统计
        recipients[recipient]['count'] += 1
        recipients[recipient]['amount'] += instance.amount or Decimal('0')

        # 构建深链接
        corp_id = source_app.corp_id if source_app else ''
        deep_link = (
            f"dingtalk://dingtalkclient/page/link?url="
            f"https://aflow.dingtalk.com/dingtalk/mobile/homepage.htm?"
            f"corpid={corp_id}&dd_share=false&showmenu=false"
            f"#/approval/detail?procInsId={instance.process_instance_id}"
        ) if corp_id else ''

        create_time = instance.create_time
        if create_time and timezone.is_aware(create_time):
            create_time = timezone.localtime(create_time)

        # 添加明细
        recipients[recipient]['details'].append({
            'process_instance_id': instance.process_instance_id,
            'create_date': create_time.strftime('%Y-%m-%d') if create_time else '',
            'amount': instance.amount or Decimal('0'),
            'reason': payment_reason[:100],  # 限制长度
            'expected_date': expected_date,
            'status': instance.status,
            'originator': instance.originator_name,
            'title': instance.title,
            'deep_link': deep_link,
        })

    # 按金额倒序
    by_recipient = sorted(recipients.values(), key=lambda x: x['amount'], reverse=True)

    return {
        'summary': {
            'total_count': total_count,
            'total_amount': status_stats['total_amount'],
            'by_status': {
                'COMPLETED': status_stats['completed'],
                'RUNNING': status_stats['running'],
                'TERMINATED': status_stats['terminated'],
                'NEW': status_stats['new'],
            },
        },
        'by_recipient': by_recipient,
    }


def get_previous_day_range(base_date=None):
    """按项目时区统计前一自然日。"""
    base_date = base_date or (timezone.localdate() if settings.USE_TZ else datetime.now().date())
    day = base_date - timedelta(days=1)
    start, end = datetime.combine(day, datetime.min.time()), datetime.combine(day, datetime.max.time())
    if settings.USE_TZ:
        start, end = timezone.make_aware(start), timezone.make_aware(end)
    return {"start": start, "end": end, "label": day.isoformat(), "start_date": day, "end_date": day}
