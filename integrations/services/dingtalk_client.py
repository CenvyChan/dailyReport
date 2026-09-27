"""钉钉企业内部应用客户端（旧版服务端 API）：access_token 缓存 + 审批实例列表/详情。

requests 惰性导入，未安装时给出清晰错误，也便于测试桩替换本客户端方法。
"""

import logging
import time

logger = logging.getLogger("integrations")

BASE = "https://oapi.dingtalk.com"


class DingtalkError(RuntimeError):
    pass


def _requests():
    try:
        import requests
    except ImportError as exc:  # pragma: no cover
        raise DingtalkError("未安装 requests，无法调用钉钉接口。") from exc
    return requests


class DingtalkClient:
    def __init__(self, app):
        self.app = app
        self._token = None
        self._expire_at = 0.0

    def token(self):
        now = time.time()
        if self._token and now < self._expire_at - 60:
            return self._token
        from integrations.crypto import decrypt

        resp = _requests().get(
            f"{BASE}/gettoken",
            params={"appkey": self.app.app_key, "appsecret": decrypt(self.app.app_secret)},
            timeout=15,
        )
        data = resp.json()
        if data.get("errcode") != 0:
            raise DingtalkError(f"获取钉钉 access_token 失败：{data}")
        self._token = data["access_token"]
        self._expire_at = now + int(data.get("expires_in", 7200))
        return self._token

    def list_instance_ids(self, process_code, start_ms, end_ms):
        ids = []
        cursor = 0
        while True:
            resp = _requests().post(
                f"{BASE}/topapi/processinstance/listids",
                params={"access_token": self.token()},
                json={"process_code": process_code, "start_time": start_ms, "end_time": end_ms, "size": 20, "cursor": cursor},
                timeout=20,
            )
            data = resp.json()
            if data.get("errcode") != 0:
                raise DingtalkError(f"拉取审批实例列表失败（{process_code}）：{data}")
            result = data.get("result", {}) or {}
            ids.extend(result.get("list", []) or [])
            next_cursor = result.get("next_cursor")
            if next_cursor is None:
                break
            cursor = next_cursor
        return ids

    def get_instance(self, process_instance_id):
        resp = _requests().post(
            f"{BASE}/topapi/processinstance/get",
            params={"access_token": self.token()},
            json={"process_instance_id": process_instance_id},
            timeout=20,
        )
        data = resp.json()
        if data.get("errcode") != 0:
            raise DingtalkError(f"拉取审批实例详情失败（{process_instance_id}）：{data}")
        return data.get("process_instance", {}) or {}
