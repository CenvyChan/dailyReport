"""构建付款申请报表的钉钉互动卡片。

使用钉钉互动卡片高级版，提供更美观、结构化的数据展示。
卡片模板需要在钉钉开放平台创建，本模块负责生成卡片数据。

参考文档:
- 卡片搭建平台: https://open-dev.dingtalk.com/fe/card
- 发送接口: https://open.dingtalk.com/document/orgapp/message-card-sending-and-updating
- 示例仓库: https://github.com/open-dingtalk/dingtalk-card-examples
"""

import logging
from decimal import Decimal
from typing import Dict, List, Any

logger = logging.getLogger("integrations")


def _format_money(amount, compact=False):
    """格式化金额。

    Args:
        amount: 金额
        compact: 是否使用紧凑格式(如 1.5M)
    """
    if amount is None or amount == 0:
        return '¥0'

    amount_float = float(amount)

    if compact:
        if amount_float >= 1_000_000:
            return f"¥{amount_float/1_000_000:.1f}M"
        elif amount_float >= 1_000:
            return f"¥{amount_float/1_000:.1f}K"

    return f"¥{amount_float:,.2f}"


def _format_status(status):
    """格式化状态为卡片标签。"""
    status_config = {
        'COMPLETED': {'text': '已完成', 'color': '#52C41A'},  # 绿色
        'RUNNING': {'text': '进行中', 'color': '#1890FF'},    # 蓝色
        'TERMINATED': {'text': '已终止', 'color': '#FF4D4F'},  # 红色
        'NEW': {'text': '新建', 'color': '#FAAD14'},          # 橙色
    }
    return status_config.get(status, {'text': status, 'color': '#999999'})


def build_payment_card_data(data: Dict[str, Any], period_info: Dict[str, Any],
                           report_type: str = 'week') -> Dict[str, Any]:
    """构建付款申请报表的卡片数据（审批卡片样式）。

    参考钉钉审批卡片设计，使用状态标签、循环列表等组件。

    Args:
        data: analyze_payment_applications 返回的数据
        period_info: 周期信息
        report_type: 'week' 或 'month'

    Returns:
        dict: 卡片数据，用于填充卡片模板变量
    """
    summary = data['summary']

    # 计算进行中占比
    total = summary['total_count']
    running_count = summary['by_status'].get('RUNNING', 0)
    completed_count = summary['by_status'].get('COMPLETED', 0)
    terminated_count = summary['by_status'].get('TERMINATED', 0)
    running_percent = int(running_count / total * 100) if total > 0 else 0

    # 卡片标题和时间范围（审批卡片样式）
    card_title = f"💰 付款申请{'周报' if report_type == 'week' else '月报'}"
    period_text = (
        f"{period_info['label']} "
        f"({period_info['start_date'].strftime('%m-%d')} 至 "
        f"{period_info['end_date'].strftime('%m-%d')})"
    )

    # 状态列表（审批卡片的状态展示）
    status_list = [
        {
            "status_icon": "✅",
            "status_text": "已完成",
            "count": completed_count,
            "amount": _format_money(summary.get('completed_amount', 0)),
            "color": "#52C41A"
        },
        {
            "status_icon": "🔄",
            "status_text": "进行中",
            "count": running_count,
            "amount": _format_money(summary.get('running_amount', 0)),
            "color": "#1890FF"
        },
        {
            "status_icon": "❌",
            "status_text": "已终止",
            "count": terminated_count,
            "amount": _format_money(summary.get('terminated_amount', 0)),
            "color": "#FF4D4F"
        },
    ]

    # Top 5 收款人（审批卡片的列表项样式）
    rank_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
    top_payees = []

    for idx, recipient_data in enumerate(data['by_recipient'][:5], start=1):
        recipient = recipient_data['recipient']
        count = recipient_data['count']
        amount = _format_money(recipient_data['amount'])

        # 获取最新一条申请
        latest_detail = recipient_data['details'][0] if recipient_data['details'] else None

        if latest_detail:
            status_info = _format_status(latest_detail['status'])
            latest_date = latest_detail['create_date']  # 格式: "10-22"
            latest_amount = _format_money(latest_detail['amount'])
            status_icon = {
                '已完成': '✅',
                '进行中': '🔄',
                '已终止': '❌',
                '新建': '📝'
            }.get(status_info['text'], '❓')
            status_text = status_info['text']
        else:
            latest_date = ''
            latest_amount = ''
            status_icon = ''
            status_text = ''

        top_payees.append({
            "rank": idx,
            "rank_emoji": rank_emojis[idx-1],
            "payee_name": recipient,
            "count": count,
            "amount": amount,
            "latest_date": latest_date,
            "latest_amount": latest_amount,
            "status_icon": status_icon,
            "status_text": status_text
        })

    # 返回卡片数据（符合审批卡片字段命名）
    return {
        # 卡片头部
        "card_title": card_title,
        "period": period_text,

        # 统计概览
        "total_count": total,
        "total_amount": _format_money(summary['total_amount']),
        "progress_percent": f"{running_percent}%",
        "progress_detail": f"({running_count}/{total})",

        # 状态列表
        "status_list": status_list,

        # Top 5 收款人
        "top_payees": top_payees,
        "remaining_count": max(0, len(data['by_recipient']) - 5),

        # 按钮链接（占位符，需要配置真实链接）
        "excel_download_url": "dingtalk://dingtalkclient/page/link?url=https://example.com/download",
        "detail_page_url": "https://example.com/payment-report/detail"
    }


def build_payment_card_template_v1() -> Dict[str, Any]:
    """构建付款申请报表卡片模板 V1（简洁版）。

    这是一个基础模板定义，需要在钉钉开放平台的卡片搭建器中创建。
    本方法返回的是模板结构参考，用于指导手动搭建。

    Returns:
        dict: 卡片模板结构定义（用于参考，非直接提交）
    """
    return {
        "type": "interactive_card",
        "templateVersion": "v1",
        "layout": {
            "header": {
                "type": "header",
                "title": "${title}",
                "subtitle": "${dateRange}",
                "icon": "https://your-domain.com/icon.png",  # 需要替换为实际图标URL
            },
            "body": [
                # 统计概览 - 三列布局
                {
                    "type": "columns",
                    "columns": [
                        {
                            "type": "stat_card",
                            "icon": "${stats[0].icon}",
                            "label": "${stats[0].label}",
                            "value": "${stats[0].value}",
                            "unit": "${stats[0].unit}",
                        },
                        {
                            "type": "stat_card",
                            "icon": "${stats[1].icon}",
                            "label": "${stats[1].label}",
                            "value": "${stats[1].value}",
                            "unit": "${stats[1].unit}",
                        },
                        {
                            "type": "stat_card",
                            "icon": "${stats[2].icon}",
                            "label": "${stats[2].label}",
                            "value": "${stats[2].value}",
                            "unit": "${stats[2].unit}",
                        },
                    ],
                },
                # 分隔线
                {
                    "type": "divider",
                },
                # Top 5 标题
                {
                    "type": "text",
                    "content": "🏆 Top 5 收款人",
                    "size": "large",
                    "weight": "bold",
                },
                # Top 5 列表 - 循环渲染
                {
                    "type": "loop",
                    "dataSource": "${topRecipients}",
                    "template": {
                        "type": "container",
                        "backgroundColor": "#F7F8FA",
                        "padding": "12px",
                        "margin": "8px 0",
                        "borderRadius": "8px",
                        "children": [
                            {
                                "type": "text",
                                "content": "${item.rank}. ${item.name}",
                                "size": "medium",
                                "weight": "bold",
                            },
                            {
                                "type": "text",
                                "content": "${item.count}条 | ${item.amount}",
                                "size": "small",
                                "color": "#666666",
                            },
                            # 条件渲染：如果有最新申请
                            {
                                "type": "condition",
                                "condition": "${item.latest}",
                                "true": {
                                    "type": "text",
                                    "content": "[最新] ${item.latest.date} ${item.latest.amount} ${item.latest.status_text}",
                                    "size": "small",
                                    "color": "${item.latest.status_color}",
                                },
                            },
                        ],
                    },
                },
                # 剩余收款人提示
                {
                    "type": "condition",
                    "condition": "${remainingRecipients} > 0",
                    "true": {
                        "type": "text",
                        "content": "...还有 ${remainingRecipients} 个收款人，详见Excel报表",
                        "size": "small",
                        "color": "#999999",
                    },
                },
            ],
            "footer": {
                "type": "buttons",
                "buttons": [
                    {
                        "type": "button",
                        "text": "📥 下载Excel",
                        "actionType": "callback",
                        "actionData": {"action": "download_excel"},
                    },
                ],
            },
        },
    }


def send_interactive_card(client, group_id: str, card_data: Dict[str, Any],
                         template_id: str = None) -> Dict[str, Any]:
    """发送互动卡片到钉钉群。

    Args:
        client: DingtalkClient 实例
        group_id: 群 openConversationId
        card_data: 卡片数据（由 build_payment_card_data 生成）
        template_id: 卡片模板ID（在钉钉开放平台创建后获得）

    Returns:
        dict: 发送结果

    Raises:
        ValueError: 如果未提供 template_id
    """
    if not template_id:
        raise ValueError("必须提供 template_id，请先在钉钉开放平台创建卡片模板")

    # 构建卡片发送请求
    payload = {
        "cardTemplateId": template_id,
        "outTrackId": f"payment_report_{card_data.get('dateRange', '')}",  # 唯一追踪ID
        "conversationType": 1,  # 1: 群聊
        "conversationId": group_id,
        "cardData": {
            "cardParamMap": card_data,  # 填充模板变量
        },
        "atOpenIds": [],  # 可选：@用户
    }

    # 调用卡片发送接口
    result = client.post('/v1.0/card/instances', payload)
    logger.info(f"互动卡片已发送到群 {group_id}: {result}")

    return result


# ============================================================================
# 渐进式迁移方案：先支持卡片，保留文本消息作为降级方案
# ============================================================================

def should_use_card(dingtalk_app) -> bool:
    """判断是否应该使用互动卡片。

    如果配置了 card_template_id，则使用卡片；否则降级为文本消息。
    """
    return hasattr(dingtalk_app, 'card_template_id') and bool(dingtalk_app.card_template_id)
