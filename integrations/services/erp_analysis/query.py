"""复用已登录金蝶 SDK，保留移植包的报表协议与分页保护。"""

import hashlib
import json
import re

from integrations.services.kingdee_client import KingdeeError

SERVER_ROW_LIMIT = 10000
PAGE_SIZE = 2000
REPORT_SERVICE = "Kingdee.BOS.WebApi.ServicesStub.DynamicFormService.GetSysReportData"


class ModuleUnavailable(KingdeeError):
    pass


def decode(raw):
    try:
        return json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    except (ValueError, TypeError) as exc:
        raise KingdeeError("金蝶分析查询返回非 JSON 数据") from exc


def check_error(data, scene):
    if isinstance(data, dict):
        status = data.get("ResponseStatus")
        if isinstance(status, dict) and status.get("IsSuccess") is False:
            message = "; ".join(
                str(item.get("Message", "")) for item in status.get("Errors", []) if isinstance(item, dict)
            )
            error = ModuleUnavailable if "未购买" in message else KingdeeError
            raise error(f"{scene}：{message or '金蝶返回失败状态'}")
        for key in ("Result", "Data"):
            if key in data:
                check_error(data[key], scene)
    elif isinstance(data, list) and data:
        check_error(data[0], scene)


def validate_rows(rows, field_keys, scene):
    if not isinstance(rows, list):
        raise KingdeeError(f"{scene}：缺少二维 Rows 数据，不能视作空报告")
    width = len(field_keys.split(","))
    for row in rows:
        if not isinstance(row, list) or len(row) != width:
            raise KingdeeError(f"{scene}：字段列数与 FieldKeys 不一致，不能生成不完整报告")
    return rows


class AnalysisQuery:
    def __init__(self, sdk):
        self.sdk = sdk
        # 仅影响本任务的 SDK 实例，不改变原有同步任务的默认超时。
        sdk.connectTimeout = 30
        sdk.requestTimeout = 300

    def bill(self, form_id, fields, filter_string):
        rows, start, previous = [], 0, None
        while True:
            data = decode(
                self.sdk.ExecuteBillQuery(
                    {
                        "FormId": form_id,
                        "FieldKeys": fields,
                        "FilterString": filter_string,
                        "OrderString": "",
                        "TopRowCount": 0,
                        "StartRow": start,
                        "Limit": PAGE_SIZE,
                    }
                )
            )
            check_error(data, form_id)
            batch = validate_rows(data, fields, form_id)
            if len(rows) + len(batch) >= SERVER_ROW_LIMIT:
                raise KingdeeError(
                    f"{form_id}：查询累计触及 {SERVER_ROW_LIMIT} 行硬上限，需进一步按日期或单号分片；禁止静默截断"
                )
            fingerprint = self.fingerprint(batch)
            if fingerprint and fingerprint == previous:
                raise KingdeeError(f"{form_id}：分页游标未前进，禁止重复累计")
            rows.extend(batch)
            if len(batch) < PAGE_SIZE:
                return rows
            previous = fingerprint
            start += len(batch)

    @staticmethod
    def fingerprint(rows):
        return (
            hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()).hexdigest() if rows else None
        )

    def report(self, form_id, fields, model):
        rows, start, previous = [], 0, None
        while True:
            params = {
                "FieldKeys": fields,
                "SchemeId": "",
                "StartRow": start,
                "Limit": SERVER_ROW_LIMIT,
                "IsVerifyBaseDataField": "true",
                "FilterString": [],
                "Model": model,
            }
            data = decode(self.sdk.PostJson(REPORT_SERVICE, {"parameters": [form_id, json.dumps(params)]}))
            check_error(data, form_id)
            container = data
            if isinstance(data, dict):
                container = (
                    data.get("Result")
                    if isinstance(data.get("Result"), dict) and "Rows" in data["Result"]
                    else data.get("Data", data)
                )
                if not isinstance(container, dict) or "Rows" not in container:
                    raise KingdeeError(f"{form_id}：报表响应缺少 Rows")
                batch, expected = container["Rows"], int(container.get("RowCount") or 0)
            else:
                batch, expected = data, 0
            validate_rows(batch, fields, form_id)
            fingerprint = self.fingerprint(batch)
            if fingerprint and fingerprint == previous:
                raise KingdeeError(f"{form_id}：报表游标未前进，禁止重复累计")
            rows.extend(batch)
            start += len(batch)
            if not batch:
                if expected and start < expected:
                    raise KingdeeError(f"{form_id}：报表提前结束，仅获得 {start}/{expected} 行")
                return rows
            if expected and start >= expected:
                return rows
            if len(batch) < SERVER_ROW_LIMIT:
                if expected and start < expected:
                    raise KingdeeError(f"{form_id}：报表结果不完整，仅获得 {start}/{expected} 行")
                return rows
            previous = fingerprint

    def organization(self, number):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", number or ""):
            raise KingdeeError("组织编码为空或含非法字符，请检查公司金蝶组织绑定")
        rows = self.bill("ORG_Organizations", "FORGID,FNumber,FName", f"FNumber = '{number}'")
        matches = [row for row in rows if str(row[1]).strip() == number]
        if len(matches) != 1 or not str(matches[0][0] or "").isdigit():
            raise KingdeeError(f"组织 {number} 查不到唯一内部 ID；不能把组织编码当成内部 ID")
        return {"id": str(matches[0][0]), "number": str(matches[0][1]), "name": str(matches[0][2] or number)}
