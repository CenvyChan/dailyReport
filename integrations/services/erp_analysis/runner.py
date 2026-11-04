"""持久化队列、独立报告生成、下载归档与独立通知检查点。"""

import json
import logging
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from django.conf import settings
from django.db import IntegrityError, transaction
from django.template.loader import render_to_string
from django.utils import timezone

from integrations.models import ErpAnalysisSchedule, ErpAnalysisTask, KingdeeOrgBinding
from integrations.services.dingtalk_client import DingtalkClient
from integrations.services.kingdee_client import build_sdk

from .catalog import REPORT_KINDS, validate_kinds
from .common import period_window, serializable
from .presentation import trend_chart
from .public import bundle_name, snapshot_url
from .query import AnalysisQuery, ModuleUnavailable
from .sources import analyze

logger = logging.getLogger("integrations")


def enqueue(company, period, kinds, *, actor=None, deduplication_key=None, notification_group=None, window_months=12):
    validate_kinds(kinds)
    period_window(period, window_months)
    if period.day != 1 or not 2000 <= period.year <= 2999:
        raise ValueError("请选择有效分析月份")
    binding = (
        KingdeeOrgBinding.objects.select_related("account")
        .filter(company=company, is_active=True, account__is_active=True)
        .first()
    )
    if not binding:
        raise ValueError("本公司未配置启用的金蝶账套及组织绑定，请先在集成配置中设置")
    if deduplication_key:
        existing = ErpAnalysisTask.objects.filter(deduplication_key=deduplication_key).first()
        if existing:
            return existing
    values = {
        "company": company,
        "account": binding.account,
        "org_number": binding.org_number,
        "org_name": binding.org_name,
        "period": period,
        "window_months": window_months,
        "report_kinds": kinds,
        "requested_by": actor,
        "deduplication_key": deduplication_key,
        "notification_group": notification_group,
        "notification_status": ErpAnalysisTask.NotificationStatus.PENDING
        if notification_group
        else ErpAnalysisTask.NotificationStatus.NONE,
    }
    try:
        with transaction.atomic():
            return ErpAnalysisTask.objects.create(**values)
    except IntegrityError:
        if not deduplication_key:
            raise
        return ErpAnalysisTask.objects.get(deduplication_key=deduplication_key)


def report_context(task, kind):
    return {
        "task": task,
        "kind": kind,
        "title": REPORT_KINDS[kind]["name"],
        "report": task.results[kind]["report"],
        "chart": trend_chart(kind, task.results[kind]["report"]),
    }


def render_report(task, kind):
    return render_to_string("reports/erp_analysis_report.html", report_context(task, kind))


def storage_root():
    return Path(settings.BASE_DIR) / "data" / "erp_analysis"


def bundle_file(task):
    expected = (storage_root() / f"task-{task.pk}" / "reports.zip").resolve()
    if not task.bundle_path or Path(task.bundle_path).resolve() != expected or not expected.is_file():
        raise FileNotFoundError("分析下载包不存在，请检查任务归档")
    return expected


def archive(task):
    folder = storage_root() / f"task-{task.pk}"
    folder.mkdir(parents=True, exist_ok=True)
    pending = folder / "reports.zip.tmp"
    target = folder / "reports.zip"
    with ZipFile(pending, "w", ZIP_DEFLATED) as bundle:
        manifest = {
            "task_id": task.pk,
            "company": task.company.code,
            "period": str(task.period),
            "window_months": task.window_months,
            "account": task.account.name,
            "organization": task.org_number,
            "generated_at": str(timezone.now()),
            "reports": {
                kind: {"name": REPORT_KINDS[kind]["name"], "status": result["status"], "error": result.get("error", "")}
                for kind, result in task.results.items()
            },
        }
        bundle.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for kind, result in task.results.items():
            if result["status"] == "SUCCESS":
                name = REPORT_KINDS[kind]["name"]
                bundle.writestr(f"{name}.html", render_report(task, kind))
                bundle.writestr(f"{name}.json", json.dumps(result["report"], ensure_ascii=False, indent=2))
    pending.replace(target)
    return str(target.resolve())


def process_task(task_id):
    claimed = ErpAnalysisTask.objects.filter(pk=task_id, status=ErpAnalysisTask.Status.PENDING).update(
        status=ErpAnalysisTask.Status.RUNNING, started_at=timezone.now(), error=""
    )
    if not claimed:
        return None
    task = ErpAnalysisTask.objects.select_related("company", "account", "notification_group__app").get(pk=task_id)
    try:
        validate_kinds(task.report_kinds)
        if not task.account.is_active or not task.company.is_active:
            raise ValueError("公司或金蝶账套已停用")
        query = AnalysisQuery(build_sdk(task.account))
        org = query.organization(task.org_number)
        task.org_name = org["name"]
        for kind in task.report_kinds:
            if task.results.get(kind, {}).get("status") == "SUCCESS":
                continue
            try:
                data = analyze(kind, query, org, task.period, task.window_months)
                task.results[kind] = {"status": "SUCCESS", "report": serializable(data)}
            except ModuleUnavailable as exc:
                task.results[kind] = {"status": "SKIPPED", "error": str(exc)[:1000]}
            except Exception as exc:
                logger.exception("经营分析报告失败 task=%s kind=%s", task.pk, kind)
                task.results[kind] = {"status": "FAILED", "error": str(exc)[:1000]}
            task.save(update_fields=["results", "org_name", "updated_at"])
        successes = sum(result["status"] == "SUCCESS" for result in task.results.values())
        task.status = (
            ErpAnalysisTask.Status.SUCCESS
            if successes == len(task.report_kinds)
            else ErpAnalysisTask.Status.PARTIAL
            if successes
            else ErpAnalysisTask.Status.FAILED
        )
        task.bundle_path = archive(task)
    except Exception as exc:
        logger.exception("经营分析任务失败 task=%s", task.pk)
        task.status, task.error = ErpAnalysisTask.Status.FAILED, str(exc)[:1000]
    task.finished_at = timezone.now()
    task.save(update_fields=["status", "error", "bundle_path", "finished_at", "updated_at"])
    if task.notification_status == ErpAnalysisTask.NotificationStatus.PENDING:
        notify(task.pk)
    return task


def notify(task_id, *, retry=False):
    allowed = [ErpAnalysisTask.NotificationStatus.PENDING]
    if retry:
        allowed.append(ErpAnalysisTask.NotificationStatus.FAILED)
    task = ErpAnalysisTask.objects.select_related("company", "notification_group__app").get(pk=task_id)
    if task.notification_status not in allowed or task.status in (task.Status.PENDING, task.Status.RUNNING):
        return
    # 一个工作进程处理通知；不自动重发网络超时后的不确定回执。
    try:
        group = task.notification_group
        if not group:
            raise ValueError("通知群已删除，未发送")
        candidate = ErpAnalysisSchedule(company=task.company, report_kinds=task.report_kinds, notification_group=group)
        candidate.clean()
        if not group.app.robot_code:
            raise ValueError("通知应用未配置机器人 Code")
        if not settings.PUBLIC_BASE_URL:
            raise ValueError("未设置 PUBLIC_BASE_URL，无法生成分析入口链接")
        client = DingtalkClient(group.app)
        success_count = sum(item["status"] == "SUCCESS" for item in task.results.values())
        statuses = {"SUCCESS": "已生成", "FAILED": "失败", "SKIPPED": "模块未购买，跳过"}
        contents = []
        for kind in task.report_kinds:
            item = REPORT_KINDS[kind]
            state = statuses.get(task.results.get(kind, {}).get("status"), "未生成")
            contents.append(f"{item['name']}（{state}）：{item['description']}")
        window = period_window(task.period, task.window_months)
        text = (
            f"ZIP 分析包：{bundle_name(task)}\n"
            f"分析期间：{window[0][0]} ~ {window[-1][1]}\n"
            f"已生成 {success_count}/{len(task.report_kinds)} 份。包含以下分析：\n"
            + "\n".join(contents)
            + "\n点击查看在线快照，并下载 ZIP（自包含 HTML 报告 + JSON 明细 + 结果清单）。链接 30 天有效，请勿对外转发。"
        )
        client.post(
            "/v1.0/robot/groupMessages/send",
            {
                "msgKey": "sampleLink",
                "robotCode": group.app.robot_code,
                "openConversationId": group.open_conversation_id,
                "msgParam": json.dumps(
                    {
                        "title": f"{task.company.name} {task.period:%Y-%m} 经营分析 ZIP · {task.get_status_display()}",
                        "text": text,
                        "messageUrl": snapshot_url(task),
                    },
                    ensure_ascii=False,
                ),
            },
        )
        task.notification_status, task.notification_error = task.NotificationStatus.SENT, ""
    except Exception as exc:
        logger.exception("经营分析通知失败 task=%s", task.pk)
        task.notification_status, task.notification_error = task.NotificationStatus.FAILED, str(exc)[:1000]
    task.save(update_fields=["notification_status", "notification_error", "updated_at"])


def enqueue_due(now=None):
    now = timezone.localtime(now or timezone.now())
    due = []
    for schedule in ErpAnalysisSchedule.objects.filter(enabled=True, company__is_active=True).select_related(
        "company", "notification_group__app"
    ):
        if now.day < schedule.day or (now.day == schedule.day and now.hour < schedule.hour):
            continue
        try:
            schedule.clean()
            last_month = period_window(now.date().replace(day=1), 2)[0][0]
            due.append(
                enqueue(
                    schedule.company,
                    last_month,
                    schedule.report_kinds,
                    deduplication_key=f"erp-analysis:{schedule.company_id}:{last_month:%Y-%m}",
                    notification_group=schedule.notification_group,
                )
            )
        except Exception:
            logger.exception("经营分析调度配置无效 company=%s", schedule.company_id)
    return due
