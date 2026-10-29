"""应用机器人原生 A2UI 发送器：付款与经营日报共用，无个人 DWS 依赖。"""
import json
from pathlib import Path
from uuid import uuid4

from integrations.services.dingtalk_client import DingtalkError


class DingtalkA2UIClient:
    """用当前企业应用的机器人身份直发原生 A2UI，不使用个人 OAuth。"""

    def __init__(self, client):
        self.client = client

    def check_available(self):
        if not (self.client.app.robot_code or "").strip():
            raise DingtalkError("未配置机器人 Code，不能发送 A2UI 卡片。")

    def send_card(self, group_id, frames, receipt_path, *, track_id=None):
        self.check_available()
        model = next(frame["updateDataModel"]["value"] for frame in frames
                     if "updateDataModel" in frame)
        track_id = track_id or f"payment-report-{uuid4().hex}"
        receipt_path = Path(receipt_path)
        receipt = {"outTrackId": track_id, "groupId": group_id, "flowStatus": "UNKNOWN"}

        def save():
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")

        # 请求前落盘；超时也能按追踪 ID 查证，绝不自动重发或切换发送身份。
        save()
        payload = {
            "outTrackId": track_id,
            "openSpaceId": "dtv1.card//IM_GROUP." + group_id,
            "protocolVersion": "1.0",
            "flowStatus": "FINISH",
            "summary": model.get("deliverySummary") or (
                f"{model['companyName']} · {model['reportTitle']} · {model['period']} · "
                f"{model['summary']['totalCountText']} / {model['summary']['totalAmountText']}"
            ),
            "a2uiMessages": [json.dumps(frame, ensure_ascii=False, separators=(",", ":"))
                             for frame in frames],
            "imGroupOpenDeliverModel": {"robotCode": self.client.app.robot_code},
            "imGroupOpenSpaceModel": {"supportForward": False},
        }
        try:
            response = self.client.post("/v1.0/card/ai/instances/createAndDeliver", payload)
            receipt["response"] = response
            result = response.get("result") if isinstance(response, dict) else None
            receipt["createResult"] = result
            deliveries = result.get("deliverResults") if isinstance(result, dict) else None
            if not (
                isinstance(response, dict) and response.get("success") is True
                and isinstance(result, dict) and result.get("outTrackId") == track_id
                and isinstance(deliveries, list) and len(deliveries) == 1
                and isinstance(deliveries[0], dict)
                and deliveries[0].get("spaceId") == group_id
                and deliveries[0].get("spaceType") == "IM_GROUP"
                and deliveries[0].get("success") is True
            ):
                raise DingtalkError("A2UI 机器人投递回执未确认目标群成功，请核实后再处理，不要直接重发。")
            receipt["flowStatus"] = "FINISH"
            save()
        except Exception as exc:
            receipt["error"] = str(exc)
            save()
            raise DingtalkError(
                f"A2UI 机器人发送未确认成功，outTrackId={track_id}；回执：{receipt_path}；"
                f"请先核实群消息，不要直接重发。原因：{exc}",
                code=getattr(exc, "code", None),
            ) from exc
        return receipt
