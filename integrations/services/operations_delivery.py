"""经营日报三件套投递：附件先准备，逐步落盘，不盲重发结果未知的消息。"""
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.utils import timezone

from integrations.models import ReportDelivery
from integrations.services.operations_a2ui import build_operations_a2ui_messages
from integrations.services.a2ui_robot import DingtalkA2UIClient


class OperationsDeliveryUncertain(RuntimeError):
    """远端可能已接受消息，必须人工核对，禁止自动重发。"""


def _fingerprint(snapshot):
    body = {"company": snapshot.company_id, "scope": snapshot.scope,
            "date": snapshot.report_date.isoformat(), "data": snapshot.data,
            "is_complete": snapshot.is_complete, "sync_warnings": snapshot.sync_warnings}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def deliver_operations_report(delivery, group, snapshot, client, *, render_pdf, render_excel):
    """同一 ReportDelivery 的成功阶段不重发；强制重发由调用方明确重置状态。"""
    a2ui = DingtalkA2UIClient(client)
    delivery.refresh_from_db()
    state = dict(delivery.delivery_state or {})
    if not state and delivery.attempt_count:
        raise OperationsDeliveryUncertain("旧版失败记录无法确认已发送内容，请先核对群消息，再决定是否强制重发。")
    fingerprint = _fingerprint(snapshot)
    target = {"appId": group.app_id, "groupId": group.open_conversation_id}
    if state and (state.get("fingerprint") != fingerprint or state.get("target") != target):
        raise OperationsDeliveryUncertain("重试期间快照或推送范围/目标已变更，禁止混用原投递回执，请人工核对。")
    if any((state.get(key) or {}).get("status") in ("SENDING", "UNCERTAIN")
           for key in ("card", "pdf", "excel")):
        raise OperationsDeliveryUncertain("存在正在发送或结果不明的阶段，请核对回执，不自动重复发送。")
    previous = delivery.delivery_state or {}
    claimed = {**state, "version": 1, "fingerprint": fingerprint, "target": target,
               "scope": snapshot.scope, "companyId": snapshot.company_id, "inProgress": True}
    if state.get("inProgress"):
        raise OperationsDeliveryUncertain("本条投递已被另一进程领取或此前进程中断，请人工核对。")
    if not ReportDelivery.objects.filter(pk=delivery.pk, delivery_state=previous).update(delivery_state=claimed):
        raise OperationsDeliveryUncertain("其他进程正在处理本条投递，已停止重复发送。")
    state = claimed
    directory = Path(settings.BASE_DIR) / "data/report_deliveries" / str(delivery.pk) / fingerprint[:16]

    def save():
        ReportDelivery.objects.filter(pk=delivery.pk).update(delivery_state=state)
        delivery.delivery_state = state

    try:
        directory.mkdir(parents=True, exist_ok=True)
        a2ui.check_available()
        frames = build_operations_a2ui_messages(snapshot)
        base = f"{snapshot.company.code}_{snapshot.report_date}_{snapshot.scope}_经营日报"
        pdf_path, excel_path = directory / (base + ".pdf"), directory / (base + ".xlsx")
        # 必须同时保留 PDF 和 Excel，渲染失败时停止，不以 HTML 静默替代 PDF。
        if not pdf_path.exists():
            pdf_bytes = render_pdf(snapshot, style="book")
            if not pdf_bytes.startswith(b"%PDF-"):
                raise ValueError("PDF 渲染结果不是有效 PDF 文件。")
            pdf_path.write_bytes(pdf_bytes)
        if not excel_path.exists():
            excel_bytes = render_excel(snapshot)
            if not excel_bytes.startswith(b"PK"):
                raise ValueError("Excel 导出结果不是 XLSX 文件。")
            excel_path.write_bytes(excel_bytes)
        card_path = directory / "card.a2ui.json"
        if card_path.exists():
            frames = json.loads(card_path.read_text(encoding="utf-8"))
        else:
            card_path.write_text(json.dumps(frames, ensure_ascii=False, indent=2), encoding="utf-8")
        # 上传不会在群里产生消息，可安全重试；两份附件先上传再发送卡片。
        for kind, path in (("pdf", pdf_path), ("excel", excel_path)):
            phase = state.setdefault(kind, {})
            if phase.get("status") != "SENT" and not phase.get("mediaId"):
                phase.update({"mediaId": client.upload_media(path.name, path.read_bytes()),
                              "fileName": path.name, "status": "READY"})
                save()
        card = state.setdefault("card", {})
        if card.get("status") != "SENT":
            card.update({"status": "SENDING", "outTrackId": f"operations-report-{uuid4().hex}",
                         "receiptPath": str(directory / "card.receipt.json")})
            save()
            try:
                receipt = a2ui.send_card(group.open_conversation_id, frames, card["receiptPath"],
                                         track_id=card["outTrackId"])
            except Exception as exc:
                card.update({"status": "UNCERTAIN", "error": str(exc)})
                save()
                raise OperationsDeliveryUncertain(f"A2UI 发送结果待核对：{card['outTrackId']}；{exc}") from exc
            card.update({"status": "SENT", "receipt": receipt, "sentAt": timezone.now().isoformat()})
            save()
        for kind in ("pdf", "excel"):
            phase = state[kind]
            if phase.get("status") == "SENT":
                continue
            phase["status"] = "SENDING"
            save()
            try:
                response = client.post("/v1.0/robot/groupMessages/send", {
                    "robotCode": client.app.robot_code,
                    "openConversationId": group.open_conversation_id,
                    "msgKey": "sampleFile",
                    "msgParam": json.dumps({"mediaId": phase["mediaId"], "fileName": phase["fileName"]}, ensure_ascii=False),
                })
                if response.get("errcode", 0) != 0:
                    raise RuntimeError(f"附件发送被拒绝：{response.get('errmsg', response)}")
            except Exception as exc:
                phase.update({"status": "UNCERTAIN", "error": str(exc)})
                save()
                raise OperationsDeliveryUncertain(f"{kind.upper()} 附件发送结果待核对，不重复发卡：{exc}") from exc
            phase.update({"status": "SENT", "receipt": response, "sentAt": timezone.now().isoformat()})
            save()
            (directory / f"{kind}.receipt.json").write_text(json.dumps(phase, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        state["inProgress"] = False
        save()
