"""钉钉企业内部应用客户端：旧版 oapi（审批实例）+ 新版开放平台（群消息）。

requests 惰性导入，未安装时给出清晰错误，也便于测试桩替换本客户端方法。
"""

import logging
import time

logger = logging.getLogger("integrations")

BASE = "https://oapi.dingtalk.com"
# 新版开放平台 API：token 走请求头而不是 query 参数，路径带 /v1.0 前缀
NEW_API_BASE = "https://api.dingtalk.com"


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

    def post(self, path, payload):
        """调用新版开放平台 API（api.dingtalk.com），path 形如 /v1.0/robot/groupMessages/send。

        新版接口 access_token 放请求头 x-acs-dingtalk-access-token；
        返回体 errcode 缺省为 0 表示成功，非 0 抛 DingtalkError。
        """
        resp = _requests().post(
            f"{NEW_API_BASE}{path}",
            headers={"x-acs-dingtalk-access-token": self.token()},
            json=payload,
            timeout=20,
        )
        try:
            data = resp.json()
        except ValueError as exc:
            raise DingtalkError(f"钉钉接口 {path} 返回非 JSON（HTTP {resp.status_code}）：{resp.text[:200]}") from exc
        if data.get("errcode", 0) != 0:
            raise DingtalkError(f"钉钉接口 {path} 失败：{data}")
        return data

    def upload_media(self, filename, content, media_type="file"):
        """上传机器人文件媒体，返回 media_id。

        旧版媒体上传接口仍被新版机器人文件消息兼容使用；文件消息本身
        仍通过 api.dingtalk.com/v1.0/robot/groupMessages/send 发送。
        """
        resp = _requests().post(
            f"{BASE}/media/upload",
            params={"access_token": self.token(), "type": media_type},
            files={"media": (filename, content, "text/html; charset=utf-8")},
            timeout=30,
        )
        try:
            data = resp.json()
        except ValueError as exc:
            raise DingtalkError(f"钉钉媒体上传返回非 JSON（HTTP {resp.status_code}）：{resp.text[:200]}") from exc
        if resp.status_code >= 400 or data.get("errcode", 0) != 0:
            raise DingtalkError(f"钉钉媒体上传失败：{data}")
        media_id = data.get("media_id")
        if not media_id:
            raise DingtalkError(f"钉钉媒体上传未返回 media_id：{data}")
        return media_id


def build_client(app):
    """按 DingtalkApp 构造客户端。"""

    return DingtalkClient(app)
