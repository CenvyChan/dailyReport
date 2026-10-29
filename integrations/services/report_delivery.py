"""报表推送服务：快照生成、HTML/Excel 渲染、邮件和钉钉发送。

核心功能：
- 生成不可变报表快照（集成对账计算和次日更正）
- 渲染 HTML 和 Excel
- 推送到邮件和钉钉群
- 失败重试和渠道隔离
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.models import Company
from integrations.models import ReportDelivery, ReportSnapshot
from integrations.services.reconciliation import generate_reconciliation_report

logger = logging.getLogger("integrations")

MAX_RETRY_ATTEMPTS = 5


def render_snapshot_html(snapshot: ReportSnapshot, *, standalone: bool = True) -> str:
    """渲染合并版 HTML 快照，邮件和钉钉文件消息共用同一份内容。"""
    from django.template.loader import render_to_string

    from integrations.services.operations_summary import operations_context
    return render_to_string(
        "integrations/report_snapshot_book.html" if standalone else "integrations/report_snapshot.html",
        operations_context(snapshot),
    )


def render_snapshot_book_html(snapshot: ReportSnapshot) -> str:
    """渲染「书册式」(book)风格的自包含 HTML。

    对齐 dailyreportAure 的现代极简白主题，按节分页，供 PDF 打印使用。
    与经典版(report_snapshot.html)完全独立，互不影响。
    """
    from django.template.loader import render_to_string

    from integrations.services.operations_summary import operations_context
    return render_to_string("integrations/report_snapshot_book.html", operations_context(snapshot))


def render_snapshot_pdf(snapshot: ReportSnapshot, *, style: str = "classic") -> bytes:
    """用 Chromium(playwright)把快照 HTML 渲染为多页 A4 PDF。

    钉钉 APP 无法在线预览 HTML 文件，但原生支持 PDF 预览。这里直接复用
    同一份 HTML 模板，用真实浏览器引擎渲染，保证 PDF 与网页端所见一致
    （grid/flex/SVG 等现代布局都能正确呈现，weasyprint 做不到）。

    打印背景色必须开启，否则 KPI 卡片、柱状图等依赖背景色的元素会丢色。

    style="classic" 保留兼容入口；两种风格入口均使用书册式分节报告，
    模板自带页边距与分页，Chromium 外边距保持为零。
    """
    from playwright.sync_api import sync_playwright

    if style == "book":
        html = render_snapshot_book_html(snapshot)
        margin = {"top": "0", "bottom": "0", "left": "0", "right": "0"}
    else:
        html = render_snapshot_html(snapshot)
        margin = {"top": "0", "bottom": "0", "left": "0", "right": "0"}
    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]
        )
        try:
            page = browser.new_page()
            # 等网络空闲，确保字体/SVG 都渲染完成再截 PDF。
            page.set_content(html, wait_until="networkidle")
            pdf_bytes = page.pdf(
                format="A4",
                print_background=True,
                margin=margin,
            )
        finally:
            browser.close()
    return pdf_bytes


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
    existing = ReportSnapshot.objects.filter(
        company=company,
        report_date=report_date,
        scope=scope,
    ).first()

    if existing and not force_regenerate:
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

    from integrations.services.operations_summary import build_operations_summary, build_monthly_comparison_snapshot
    reconciliation_data["operations"] = build_operations_summary(company, report_date, scope)
    reconciliation_data["monthly_comparison"] = build_monthly_comparison_snapshot(company, report_date)

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

    # 首次生成创建记录；强制重生成原地更新，保留快照 ID 和渠道发送记录，
    # 避免唯一约束冲突，也避免删除快照触发 ReportDelivery.PROTECT。
    with transaction.atomic():
        if existing:
            snapshot = existing
            snapshot.data = snapshot_data
            snapshot.sync_windows = sync_windows
            snapshot.calculation_version = "v1"
            snapshot.is_complete = is_complete
            snapshot.sync_warnings = sync_warnings
            snapshot.generated_at = timezone.now()
            snapshot.save(update_fields=[
                "data", "sync_windows", "calculation_version", "is_complete",
                "sync_warnings", "generated_at",
            ])
        else:
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
    force_resend: bool = False,
) -> list[tuple[str, str, str]]:
    """推送报表到所有渠道。

    Args:
        snapshot: 报表快照
        send_now: 立即发送，忽略收件组发送时间
        force_resend: 重置该快照的发送记录后重投。
            --force 原地更新快照时 ID 不变、ReportDelivery 仍是 SENT，
            定时链路靠这条记录防重复刷屏；手动 force 重生成是明确的「按最新内容重发」
            意图，故把已发送记录重置为 PENDING（attempt_count 归零），让渠道重新投递。
            仅手动 force 时为 True，定时任务不传此参数，行为不变。

    Returns:
        list of (channel_name, status, message)
    """
    results = []

    if force_resend:
        reset_count = ReportDelivery.objects.filter(snapshot=snapshot).update(
            status=ReportDelivery.Status.PENDING,
            attempt_count=0,
            last_error="",
            delivery_state={},
            sent_at=None,
        )
        if reset_count:
            logger.info(
                "强制重发：重置 %s 条发送记录 snapshot=%s", reset_count, snapshot.id
            )

    # 推送到邮件
    email_results = _send_to_email_channels(snapshot, send_now)
    results.extend(email_results)

    # 推送到钉钉
    dingtalk_results = _send_to_dingtalk_channels(snapshot, send_now)
    results.extend(dingtalk_results)

    return results


def backfill_missed_deliveries(
    company: Company,
    before_date,
    days: int,
    scope: str = "BOTH",
) -> list[tuple[ReportSnapshot, list[tuple[str, str, str]]]]:
    """补投早于 before_date 的、尚未成功发送的快照。

    定时链路每轮只盯「当天的目标日期」，一旦投递窗口（收件组/群配置的 send_at
    到当日 24:00）内遇到容器重启、断网或 API 故障，过了零点目标日期就滚到下一天，
    那份日报永久不会再发，也没人会收到告警。这里兜住这类丢单。

    Args:
        company: 公司
        before_date: 补发范围上界（不含）。必须传当轮的目标报表日期，
            这样今天还没到 send_at 的那份不会被补发逻辑提前发出去。
        days: 向前回溯天数
        scope: 业务范围，与快照唯一约束对齐

    Returns:
        list of (snapshot, results)，只包含实际产生了渠道动作的快照
    """
    start_date = before_date - timedelta(days=days)

    snapshots = ReportSnapshot.objects.filter(
        company=company,
        scope=scope,
        report_date__gte=start_date,
        report_date__lt=before_date,
    ).order_by("report_date")

    backfilled = []
    for snapshot in snapshots:
        # 这些快照的投递窗口早已过去，不再受 send_at 约束，判定为漏发就立即补。
        # 渠道内部按 (快照, 渠道, 目标) 判重并有 MAX_RETRY_ATTEMPTS 上限，
        # 已成功的会走 SKIPPED，不会重复刷屏，也不会无限重试。
        results = send_report_to_all_channels(snapshot, send_now=True)
        actionable = [r for r in results if r[1] != "SKIPPED"]
        if actionable:
            logger.info(
                "补发漏投快照：snapshot=%s, date=%s, 结果=%s",
                snapshot.id,
                snapshot.report_date,
                actionable,
            )
            backfilled.append((snapshot, results))

    return backfilled


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

    # 过滤业务范围：新版用 content_types (JSONField)，兼容旧版 scope 字段
    # 逻辑：快照的 scope 表示本快照包含的数据类型，收件组的 content_types
    # 表示想接收的类型。当收件组的类型列表包含快照的类型时匹配。
    if snapshot.scope == "SALES":
        mailing_lists = [ml for ml in mailing_lists if "SALES" in (ml.content_types or [])]
    elif snapshot.scope == "PURCHASE":
        mailing_lists = [ml for ml in mailing_lists if "PURCHASE" in (ml.content_types or [])]
    else:  # BOTH
        # 快照是 BOTH 时，只要收件组包含 SALES 或 PURCHASE 就匹配
        mailing_lists = list(mailing_lists)

    if not send_now:
        # 检查发送时间
        now_time = timezone.localtime().time()
        mailing_lists = [ml for ml in mailing_lists if ml.send_at <= now_time]
    else:
        mailing_lists = list(mailing_lists)

    # 没有到点的收件组就直接返回：下面的 HTML 渲染和 SMTP 连接都是无条件执行的，
    # 而本命令每 10 分钟跑一轮，不短路等于每轮白渲染一遍完整日报 HTML。
    if not mailing_lists:
        return results

    # 准备邮件内容（对所有收件组共用）
    email_subject = f"{snapshot.company.name} {snapshot.report_date:%Y年%m月%d日} 经营日报"
    email_html = render_snapshot_html(snapshot)

    # 准备 Excel 附件
    excel_bytes = None
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
        is_active=True,
    ).filter(Q(companies=snapshot.company) | Q(companies__isnull=True, company=snapshot.company)).select_related("app").distinct()

    # BOTH 快照也必须尊重群内容选择，卡片及附件都不包含未勾选的业务。
    selected = {snapshot.scope} if snapshot.scope != "BOTH" else {"SALES", "PURCHASE"}
    group_configs = [gc for gc in group_configs if selected.intersection(gc.content_types or [])]

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

        if (
            not created
            and not send_now
            and delivery.status == ReportDelivery.Status.SENT
            and _sent_before_scheduled_window(delivery, snapshot, group_config)
        ):
            # 手动提前发过（如 --now），定时窗口仍需按时再发一次；
            # 定时发出后 sent_at 晚于窗口，后续轮次不会再重复。
            delivery.status = ReportDelivery.Status.PENDING
            delivery.attempt_count = 0
            delivery.last_error = ""
            delivery.delivery_state = {}
            delivery.sent_at = None
            delivery.save()
            logger.info("定时窗口重发：snapshot=%s, target=%s 此前在窗口前已手动发送",
                        snapshot.id, group_config.name)

        if not created and delivery.status == ReportDelivery.Status.SENT:
            results.append(("钉钉", "SKIPPED", f"{group_config.name} 已发送"))
            continue

        if delivery.attempt_count >= MAX_RETRY_ATTEMPTS:
            results.append(("钉钉", "SKIPPED", f"{group_config.name} 已达重试上限"))
            continue

        if delivery.status == ReportDelivery.Status.UNCERTAIN:
            results.append(("钉钉", "SKIPPED", f"{group_config.name} 投递结果待人工核对"))
            continue

        try:
            from integrations.services.operations_a2ui import filter_snapshot_for_contents
            from integrations.services.operations_delivery import deliver_operations_report, OperationsDeliveryUncertain
            from integrations.services.snapshot_export import export_snapshot_to_excel

            scoped_snapshot = filter_snapshot_for_contents(snapshot, group_config.content_types)
            client = build_client(group_config.app)
            deliver_operations_report(
                delivery, group_config, scoped_snapshot, client,
                render_pdf=render_snapshot_pdf, render_excel=export_snapshot_to_excel,
            )
            delivery.status = ReportDelivery.Status.SENT
            delivery.attempt_count += 1
            delivery.sent_at = timezone.now()
            delivery.last_error = ""
            delivery.save()
            results.append(("钉钉", "SENT", group_config.name))
            logger.info("钉钉 A2UI/PDF/Excel 发送成功：snapshot=%s, target=%s", snapshot.id, group_config.name)
        except Exception as exc:
            from integrations.services.operations_delivery import OperationsDeliveryUncertain
            delivery.refresh_from_db()
            delivery.status = (ReportDelivery.Status.UNCERTAIN if isinstance(exc, OperationsDeliveryUncertain)
                               else ReportDelivery.Status.FAILED)
            delivery.attempt_count += 1
            delivery.last_error = str(exc)
            delivery.save()
            results.append(("钉钉", delivery.status, f"{group_config.name}: {exc}"))
            logger.exception("钉钉日报三件套发送失败：snapshot=%s, target=%s", snapshot.id, group_config.name)

    return results


def _sent_before_scheduled_window(delivery, snapshot, group_config) -> bool:
    """报表日的定时窗口是「报表日次日的 send_at」，早于它的发送视为手动提前发送。"""
    if delivery.sent_at is None:
        return False
    window = timezone.make_aware(
        datetime.combine(snapshot.report_date + timedelta(days=1), group_config.send_at)
    )
    return delivery.sent_at < window


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
