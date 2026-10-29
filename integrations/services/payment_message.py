"""构建付款申请报表的钉钉消息内容。

生成简洁、适合移动端阅读的Markdown格式消息。
"""

import logging
from decimal import Decimal

logger = logging.getLogger("integrations")


def _format_money(amount):
    """格式化金额。"""
    if amount is None or amount == 0:
        return '¥0.00'
    return f"¥{float(amount):,.2f}"


def _format_status_emoji(status):
    """将状态转换为emoji表示。"""
    status_map = {
        'COMPLETED': '✅',
        'RUNNING': '🔄',
        'TERMINATED': '❌',
        'NEW': '🆕',
    }
    return status_map.get(status, '❓')


def _format_status_text(status):
    """将状态转换为中文文本。"""
    status_map = {
        'COMPLETED': '已完成',
        'RUNNING': '进行中',
        'TERMINATED': '已终止',
        'NEW': '新建',
    }
    return status_map.get(status, status)


def _truncate_text(text, max_length=40):
    """截断文本到指定长度。"""
    if not text:
        return ''
    text = str(text).strip()
    if len(text) <= max_length:
        return text
    return text[:max_length] + '...'


def build_payment_report_message(data, period_info, report_type='week', mention_userids=None):
    """构建钉钉付款申请报表消息。

    Args:
        data: analyze_payment_applications 返回的数据
        period_info: 周期信息
        report_type: 'week' 或 'month'
        mention_userids: 要@的用户ID列表

    Returns:
        str: Markdown格式的消息内容
    """
    title = '付款申请' + dict(day='日报', week='周报', month='月报')[report_type]

    # 消息头部
    lines = [
        f"📊 {title}",
        "━━━━━━━━━━━━━━━━━━",
        f"📅 {period_info['start_date'].strftime('%Y-%m-%d')} 至 "
        f"{period_info['end_date'].strftime('%Y-%m-%d')}",
        "",
    ]

    # 总览
    summary = data['summary']
    total_amount = _format_money(summary['total_amount'])
    lines.extend([
        f"📈 总计:{summary['total_count']}条 | {total_amount}",
        f"✅ 已完成:{summary['by_status']['COMPLETED']}条 | "
        f"🔄 进行中:{summary['by_status']['RUNNING']}条",
        "",
    ])

    # 如果没有数据
    if summary['total_count'] == 0:
        lines.extend([
            "━━━━━━━━━━━━━━━━━━",
            "暂无付款申请数据",
            "━━━━━━━━━━━━━━━━━━",
        ])
        return '\n'.join(lines)

    # 按收款人汇总
    lines.extend([
        "━━━━━━━━━━━━━━━━━━",
        "💰 收款人汇总",
        "━━━━━━━━━━━━━━━━━━",
        "",
    ])

    # 限制显示前10个收款人,避免消息过长
    max_recipients = 10
    for idx, recipient_data in enumerate(data['by_recipient'][:max_recipients], start=1):
        recipient = recipient_data['recipient']
        count = recipient_data['count']
        amount = _format_money(recipient_data['amount'])

        lines.append(f"{idx}️⃣ {recipient}")
        lines.append(f"   {count}条 | {amount}")
        lines.append("")

        # 显示前5条明细
        max_details = 5
        for detail in recipient_data['details'][:max_details]:
            date = detail['create_date']
            detail_amount = _format_money(detail['amount'])
            status_emoji = _format_status_emoji(detail['status'])
            status_text = _format_status_text(detail['status'])
            reason = _truncate_text(detail['reason'], 30)

            lines.append(f"   • {date} | {detail_amount} | {status_emoji}{status_text}")
            if reason:
                lines.append(f"     {reason}")

        # 如果明细超过5条,显示省略提示
        if len(recipient_data['details']) > max_details:
            remaining = len(recipient_data['details']) - max_details
            lines.append(f"   ...还有{remaining}条申请,详见Excel报表")

        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━")
        lines.append("")

    # 如果收款人超过10个,显示省略提示
    if len(data['by_recipient']) > max_recipients:
        remaining = len(data['by_recipient']) - max_recipients
        lines.append(f"...还有{remaining}个收款人,详见Excel报表")
        lines.append("")

    # 附件提示
    lines.extend([
        "📎 Excel报表已生成",
        "   详细数据请查看附件",
        "",
    ])

    # @提醒
    if mention_userids:
        # 钉钉群消息的@格式: @userId
        mentions = ' '.join(f"@{uid}" for uid in mention_userids)
        lines.append(f"💬 {mentions} 请查收本{dict(day='日', week='周', month='月')[report_type]}付款汇总")

    return '\n'.join(lines)


def build_simple_message(data, period_info, report_type='week'):
    """构建极简版消息(用于无数据或仅通知场景)。

    Args:
        data: analyze_payment_applications 返回的数据
        period_info: 周期信息
        report_type: 'week' 或 'month'

    Returns:
        str: 简化的消息内容
    """
    title = '付款申请' + dict(day='日报', week='周报', month='月报')[report_type]
    summary = data['summary']

    lines = [
        f"📊 {title}",
        f"📅 {period_info['label']}",
        "",
        f"总计: {summary['total_count']}条 | {_format_money(summary['total_amount'])}",
    ]

    if summary['total_count'] == 0:
        lines.append("")
        lines.append("✨ 本期无付款申请")
    else:
        lines.append(f"✅ {summary['by_status']['COMPLETED']}条已完成")
        lines.append(f"🔄 {summary['by_status']['RUNNING']}条进行中")
        lines.append("")
        lines.append("📎 详细报表已发送,请查看附件")

    return '\n'.join(lines)
