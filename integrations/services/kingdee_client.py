"""金蝶 WebAPI 客户端：从 DB 的 KingdeeAccount 构造 SDK，执行单据查询。

应用运行时以配置表凭证为准，不读 KD_* 环境变量（那套仅供开发期 MCP 探查）。
SDK 惰性导入：未安装时给出清晰错误，也便于测试用桩替换 _build_sdk。
"""

import json
import logging

logger = logging.getLogger(__name__)

PAGE_SIZE = 2000  # 金蝶 ExecuteBillQuery 单次约 2000 行上限


class KingdeeError(RuntimeError):
    pass


LOGIN_SERVICE = "Kingdee.BOS.WebApi.ServicesStub.AuthService.LoginByAppSecret"


def build_sdk(account):
    """按账套凭证构造并初始化金蝶 SDK，登录建会话后返回。

    SDK 8.2.0 的 ExecuteBillQuery 依赖已建立的会话（KDService_SessionId），
    自身不会先登录；未登录直接查询会得到「会话信息已丢失」的错误信封。
    因此这里显式调 LoginByAppSecret，失败立即抛错，避免失败同步被当成
    空数据静默成功。
    """
    try:
        from k3cloud_webapi_sdk.main import K3CloudApiSdk
    except ImportError as exc:  # pragma: no cover - 依赖未装时
        raise KingdeeError("未安装 kingdee-cdp-webapi-sdk，无法连接金蝶。") from exc
    from integrations.crypto import decrypt

    sdk = K3CloudApiSdk(account.server_url)
    sdk.InitConfig(
        acct_id=account.acct_id,
        user_name=account.username,
        app_id=account.app_id,
        app_secret=decrypt(account.app_secret),
        server_url=account.server_url,
        lcid=account.lcid or 2052,
        org_num=0,
    )

    login = json.loads(
        sdk.PostJson(
            LOGIN_SERVICE,
            {
                "acctID": account.acct_id,
                "userName": account.username,
                "appId": account.app_id,
                "appSecret": decrypt(account.app_secret),
                "lcid": account.lcid or 2052,
            },
        )
    )
    if login.get("LoginResultType") != 1:
        raise KingdeeError(
            f"金蝶登录失败（{account.name}）：{login.get('Message') or login}"
        )
    return sdk


def _unwrap(raw, form_id, filter_string):
    data = raw
    if isinstance(raw, (str, bytes)):
        try:
            data = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise KingdeeError(f"金蝶查询 {form_id} 返回无法解析：{raw!r}") from exc
    if isinstance(data, list):
        # 错误响应与正常二维数组同形：[[{"Result": {"ResponseStatus": {...}}}] ]，
        # 必须先识别错误信封再当数据用，否则失败同步会被静默当成空数据。
        first = data[0] if data else None
        if isinstance(first, list) and first and isinstance(first[0], dict):
            status = (first[0].get("Result") or {}).get("ResponseStatus") or {}
            if status.get("IsSuccess") is False:
                errors = "; ".join(
                    e.get("Message", "") for e in status.get("Errors") or [] if isinstance(e, dict)
                )
                raise KingdeeError(
                    f"金蝶查询 {form_id} 失败（filter={filter_string}）：{errors or status}"
                )
        # 成功返回二维数组；空结果为 []。
        return data
    raise KingdeeError(f"金蝶查询 {form_id} 失败（filter={filter_string}）：{data}")


def query_bill(sdk, *, form_id, field_keys, filter_string, order_string="", page_size=PAGE_SIZE):
    """自动翻页执行 ExecuteBillQuery，返回二维数组（每行按 field_keys 顺序）。"""
    rows = []
    start = 0
    while True:
        raw = sdk.ExecuteBillQuery(
            {
                "FormId": form_id,
                "FieldKeys": field_keys,
                "FilterString": filter_string,
                "OrderString": order_string,
                "TopRowCount": 0,
                "StartRow": start,
                "Limit": page_size,
            }
        )
        page = _unwrap(raw, form_id, filter_string)
        rows.extend(page)
        if len(page) < page_size:
            break
        start += len(page)
    return rows
