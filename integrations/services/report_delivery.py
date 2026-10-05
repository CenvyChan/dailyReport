"""报表推送服务：快照生成、HTML/Excel 渲染、邮件和钉钉发送。

核心功能：
- 生成不可变报表快照（集成对账计算和次日更正）
- 渲染 HTML 和 Excel
- 推送到邮件和钉钉群
- 失败重试和渠道隔离
"""

import json
import logging
from datetime import timedelta
from typing import Optional

from django.db import transaction
from django.utils import timezone

from core.models import Company
from integrations.models import ReportDelivery, ReportSnapshot
from integrations.services.reconciliation import generate_reconciliation_report

logger = logging.getLogger("integrations")

MAX_RETRY_ATTEMPTS = 5


def generate_report_snapshot(
    company: Company,
    report_date,
    scope: str = "BOTH",
    force_regenerate: bool = False,
) -> ReportSnapshot:
    """生成或获取报表快照。

    Args:
        company: 公司对象
        report_date: 报表日期
        scope: "SALES" | "PURCHASE" | "BOTH"
        force_regenerate: 强制重新生成，即使已存在

    Returns:
        ReportSnapshot 对象

    Raises:
        已存在且不强制重新生成时返回现有快照
    """
    # 检查是否已存在
    if not force_regenerate:
        existing = ReportSnapshot.objects.filter(
            company=company,
            report_date=report_date,
            scope=scope,
        ).first()

        if existing:
            logger.info(
                "报表快照已存在：company=%s, date=%s, scope=%s",
                company, report_date, scope
            )
            return existing

    # 生成对账数据
    logger.info(
        "生成报表快照：company=%s, date=%s, scope=%s",
        company, report_date, scope
    )

    reconciliation_data = generate_reconciliation_report(
        company=company,
        report_date=report_date,
        scope=scope,
    )

    # 获取同步窗口信息
    from integrations.models import SyncRun
    recent_sync = SyncRun.objects.filter(
        integration=SyncRun.Integration.KINGDEE,
        company=company,
        status=SyncRun.Status.SUCCESS,
    ).order_by("-finished_at").first()

    sync_windows = {}
    is_complete = True
    sync_warnings = []

    if recent_sync:
        sync_windows = {
            "window_start": recent_sync.window_start.isoformat() if recent_sync.window_start else None,
            "window_end": recent_sync.window_end.isoformat() if recent_sync.window_end else None,
            "finished_at": recent_sync.finished_at.isoformat() if recent_sync.finished_at else None,
        }

        # 检查数据完整性
        if recent_sync.window_end and recent_sync.window_end < report_date:
            is_complete = False
            sync_warnings.append(f"金蝶同步窗口止于 {recent_sync.window_end}，未覆盖报表日期 {report_date}")
    else:
        is_complete = False
        sync_warnings.append("未找到金蝶同步记录，数据可能不完整")

    # 获取次日更正
    from integrations.models import ReportCorrection
    unreported_corrections = ReportCorrection.objects.filter(
        company=company,
        original_date=report_date,
        reported_in_snapshot__isnull=True,
    ).order_by("-detected_at")

    corrections_data = [
        {
            "type": corr.get_correction_type_display(),
            "original_value": float(corr.original_value) if corr.original_value else None,
            "new_value": float(corr.new_value) if corr.new_value else None,
            "diff_amount": float(corr.diff_amount),
            "reason": corr.reason,
            "affected_report": corr.get_affected_report_display(),
            "detected_at": corr.detected_at.isoformat(),
        }
        for corr in unreported_corrections
    ]

    # 合并数据
    snapshot_data = {
        **reconciliation_data,
        "corrections": corrections_data,
    }

    # 创建快照
    with transaction.atomic():
        snapshot = ReportSnapshot.objects.create(
            company=company,
            report_date=report_date,
            scope=scope,
            data=snapshot_data,
            sync_windows=sync_windows,
            calculation_version="v1",
            is_complete=is_complete,
            sync_warnings=sync_warnings,
        )

        # 标记更正已报告
        unreported_corrections.update(reported_in_snapshot=snapshot)

    logger.info("报表快照已创建：snapshot_id=%s", snapshot.id)
    return snapshot


def send_report_to_all_channels(
    snapshot: ReportSnapshot,
    send_now: bool = False,
) -> list[tuple[str, str, str]]:
    """推送报表到所有渠道。

    Args:
        snapshot: 报表快照
        send_now: 立即发送，忽略收件组发送时间

    Returns:
        list of (channel_name, status, message)
    """
    results = []

    # 推送到邮件
    email_results = _send_to_email_channels(snapshot, send_now)
    results.extend(email_results)

    # 推送到钉钉
    dingtalk_results = _send_to_dingtalk_channels(snapshot, send_now)
    results.extend(dingtalk_results)

    return results


def _send_to_email_channels(
    snapshot: ReportSnapshot,
    send_now: bool,
) -> list[tuple[str, str, str]]:
    """推送到邮件渠道。"""
    from django.template.loader import render_to_string
    from notifications.mailer import smtp_connection
    from notifications.models import MailingList
    from integrations.services.snapshot_export import export_snapshot_to_excel

    results = []

    # 查找到点的收件组
    mailing_lists = MailingList.objects.filter(
        company=snapshot.company,
        is_active=True,
    )

    # 过滤业务范围
    if snapshot.scope == "SALES":
        mailing_lists = mailing_lists.filter(scope__in=["SALES", "BOTH"])
    elif snapshot.scope == "PURCHASE":
        mailing_lists = mailing_lists.filter(scope__in=["PURCHASE", "BOTH"])

    if not send_now:
        # 检查发送时间
        now_time = timezone.localtime().time()
        mailing_lists = [ml for ml in mailing_lists if ml.send_at <= now_time]
    else:
        mailing_lists = list(mailing_lists)

    # 准备邮件内容（对所有收件组共用）
    email_subject = f"{snapshot.company.name} {snapshot.report_date:%Y年%m月%d日} 经营日报"
    email_html = render_to_string("integrations/report_snapshot.html", {"snapshot": snapshot})

    # 准备 Excel 附件
    excel_bytes = None
    if mailing_lists:  # 只有需要发送时才生成
        try:
            excel_bytes = export_snapshot_to_excel(snapshot)
        except Exception as e:
            logger.exception("生成 Excel 失败：snapshot=%s", snapshot.id)

    # 建立 SMTP 连接（复用）
    connection = None
    try:
        connection = smtp_connection()
    except Exception as e:
        logger.exception("建立 SMTP 连接失败")
        for ml in mailing_lists:
            results.append(("邮件", "FAILED", f"{ml.name}: SMTP 连接失败 - {e}"))
        return results

    for mailing_list in mailing_lists:
        target_id = str(mailing_list.id)

        # 检查是否已发送
        delivery, created = ReportDelivery.objects.get_or_create(
            snapshot=snapshot,
            channel=ReportDelivery.Channel.EMAIL,
            target_identifier=target_id,
            defaults={
                "target_display": mailing_list.name,
                "status": ReportDelivery.Status.PENDING,
            },
        )

        if not created and delivery.status == ReportDelivery.Status.SENT:
            results.append(("邮件", "SKIPPED", f"{mailing_list.name} 已发送"))
            continue

        if delivery.attempt_count >= MAX_RETRY_ATTEMPTS:
            results.append(("邮件", "SKIPPED", f"{mailing_list.name} 已达重试上限"))
            continue

        # 发送邮件
        try:
            from django.core.mail import EmailMessage

            msg = EmailMessage(
                subject=email_subject,
                body=email_html,
                from_email=None,  # 使用 settings.DEFAULT_FROM_EMAIL
                to=mailing_list.recipient_list(),
                cc=mailing_list.cc_list(),
                connection=connection,
            )
            msg.content_subtype = "html"

            # 附加 Excel
            if excel_bytes and mailing_list.attach_workbook:
                filename = f"{snapshot.company.code}_{snapshot.report_date}_report.xlsx"
                msg.attach(filename, excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

            msg.send()

            delivery.status = ReportDelivery.Status.SENT
            delivery.attempt_count += 1
            delivery.sent_at = timezone.now()
            delivery.save()

            results.append(("邮件", "SENT", mailing_list.name))
            logger.info("邮件发送成功：snapshot=%s, target=%s", snapshot.id, mailing_list.name)

        except Exception as e:
            delivery.status = ReportDelivery.Status.FAILED
            delivery.attempt_count += 1
            delivery.last_error = str(e)
            delivery.save()

            results.append(("邮件", "FAILED", f"{mailing_list.name}: {e}"))
            logger.exception("邮件发送失败：snapshot=%s, target=%s", snapshot.id, mailing_list.name)

    return results


def _send_to_dingtalk_channels(
    snapshot: ReportSnapshot,
    send_now: bool,
) -> list[tuple[str, str, str]]:
    """推送到钉钉渠道。"""
    from integrations.models import DingtalkGroupConfig
    from integrations.services.dingtalk_client import build_client

    results = []

    # 查找到点的群配置
    group_configs = DingtalkGroupConfig.objects.filter(
        company=snapshot.company,
        is_active=True,
    ).select_related("app")

    # 过滤业务范围
    if snapshot.scope == "SALES":
        group_configs = group_configs.filter(scope__in=["SALES", "BOTH"])
    elif snapshot.scope == "PURCHASE":
        group_configs = group_configs.filter(scope__in=["PURCHASE", "BOTH"])

    if not send_now:
        # 检查发送时间
        now_time = timezone.localtime().time()
        group_configs = [gc for gc in group_configs if gc.send_at <= now_time]
    else:
        group_configs = list(group_configs)

    for group_config in group_configs:
        target_id = str(group_config.id)

        # 检查是否已发送
        delivery, created = ReportDelivery.objects.get_or_create(
            snapshot=snapshot,
            channel=ReportDelivery.Channel.DINGTALK,
            target_identifier=target_id,
            defaults={
                "target_display": group_config.name,
                "status": ReportDelivery.Status.PENDING,
            },
        )

        if not created and delivery.status == ReportDelivery.Status.SENT:
            results.append(("钉钉", "SKIPPED", f"{group_config.name} 已发送"))
            continue

        if delivery.attempt_count >= MAX_RETRY_ATTEMPTS:
            results.append(("钉钉", "SKIPPED", f"{group_config.name} 已达重试上限"))
            continue

        # 发送钉钉群消息
        try:
            client = build_client(group_config.app)

            # 构建精简摘要
            markdown_text = _build_dingtalk_markdown(snapshot)

            # 应用机器人群消息接口（新版开放平台）：
            # msgKey 固定 sampleMarkdown；msgParam 是 JSON 字符串，机器人 capabilities
            # 里 markdown 消息的 title 进群消息卡片标题，text 是正文；
            # robotCode 对企业内部应用而言就是应用的 AppKey。
            response = client.post(
                "/v1.0/robot/groupMessages/send",
                {
                    "robotCode": group_config.app.app_key,
                    "openConversationId": group_config.open_conversation_id,
                    "msgKey": "sampleMarkdown",
                    "msgParam": json.dumps(
                        {"title": f"{snapshot.company.name} 经营日报 {snapshot.report_date}", "text": markdown_text},
                        ensure_ascii=False,
                    ),
                },
            )

            # 新版接口成功时 errcode 缺省为 0（客户端 post 已校验非 0 抛错），此处兜底
            if response.get("errcode", 0) == 0:
                delivery.status = ReportDelivery.Status.SENT
                delivery.attempt_count += 1
                delivery.sent_at = timezone.now()
                delivery.save()

                results.append(("钉钉", "SENT", group_config.name))
                logger.info("钉钉发送成功：snapshot=%s, target=%s", snapshot.id, group_config.name)
            else:
                raise Exception(f"钉钉 API 返回错误：{response.get('errmsg', 'Unknown error')}")

        except Exception as e:
            delivery.status = ReportDelivery.Status.FAILED
            delivery.attempt_count += 1
            delivery.last_error = str(e)
            delivery.save()

            results.append(("钉钉", "FAILED", f"{group_config.name}: {e}"))
            logger.exception("钉钉发送失败：snapshot=%s, target=%s", snapshot.id, group_config.name)

    return results


def _build_dingtalk_markdown(snapshot: ReportSnapshot) -> str:
    """构建钉钉 Markdown 消息内容。"""
    lines = [
        f"# {snapshot.company.name} 经营日报",
        f"**报表日期**: {snapshot.report_date}",
        "",
    ]

    # 数据完整性警告
    if not snapshot.is_complete:
        lines.append("⚠️ **数据不完整**")
        for warning in snapshot.sync_warnings:
            lines.append(f"- {warning}")
        lines.append("")

    # 销售摘要
    if "sales" in snapshot.data:
        sales = snapshot.data["sales"]
        lines.extend([
            "## 📈 销售对账",
            f"- 日报笔数: {sales['daily_coverage']['total_reports']}",
            f"- 日报金额: {sales['daily_coverage']['total_amount']:.2f}",
            f"- 已关联: {sales['daily_coverage']['covered_amount']:.2f}",
        ])
        coverage = sales['daily_coverage']['coverage_rate']
        if coverage is not None:
            lines.append(f"- 覆盖率: {coverage:.1f}%")
        lines.extend([
            "",
            f"**月度对账**",
            f"- 系统金额: {sales['month_diff']['system_amount']:.2f}",
            f"- 金蝶金额: {sales['month_diff']['k3_amount']:.2f}",
            f"- 差额: {sales['month_diff']['diff_amount']:.2f}",
            "",
        ])

    # 采购摘要
    if "purchase" in snapshot.data:
        purchase = snapshot.data["purchase"]
        lines.extend([
            "## 📉 采购对账",
            f"- 日报笔数: {purchase['daily_coverage']['total_reports']}",
            f"- 日报金额: {purchase['daily_coverage']['total_amount']:.2f}",
            f"- 已关联: {purchase['daily_coverage']['covered_amount']:.2f}",
        ])
        coverage = purchase['daily_coverage']['coverage_rate']
        if coverage is not None:
            lines.append(f"- 覆盖率: {coverage:.1f}%")
        lines.extend([
            "",
            f"**月度对账**",
            f"- 系统金额: {purchase['month_diff']['system_amount']:.2f}",
            f"- 金蝶金额: {purchase['month_diff']['k3_amount']:.2f}",
            f"- 差额: {purchase['month_diff']['diff_amount']:.2f}",
            "",
        ])

    # 次日更正提示
    if snapshot.data.get("corrections"):
        corr_count = len(snapshot.data["corrections"])
        lines.append(f"**次日更正**: {corr_count} 条历史变化")

    lines.extend([
        "",
        f"_生成时间: {snapshot.generated_at.strftime('%Y-%m-%d %H:%M')}_",
    ])

    return "\n".join(lines)
