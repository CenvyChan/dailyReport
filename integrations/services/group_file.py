"""新版企业存储（Storage 1.0）群文件卡片投递。

旧的 ``drive/spaces/.../files`` 需要 ``Drive.File.Write``；新版 ``storage``
链路使用 ``Storage.UploadInfo.Read`` / ``Storage.File.Write``，FNS 应用已开通。
上传成功后通过 ``convFile/conversations/files/send`` 发成会话文件卡片，
客户端即可原生预览 Excel/PDF，不需要下载。

注意：所有接口都要操作人 ``unionId``，文件卡片的发送者就是该操作人。
"""

import hashlib
import logging

import requests

logger = logging.getLogger("integrations")

BASE = "https://api.dingtalk.com"


class GroupFileError(RuntimeError):
    """stage: space / upload / commit / send。send 失败时结果可能不确定。"""

    def __init__(self, stage, message, *, request_id=""):
        super().__init__(message)
        self.stage = stage
        self.request_id = request_id


def _headers(token, *, json_body=True):
    headers = {"x-acs-dingtalk-access-token": token}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


def _request_id(response):
    return response.headers.get("x-acs-request-id", "")


def _json(response, stage):
    if response.status_code >= 400:
        raise GroupFileError(
            stage,
            f"HTTP {response.status_code}: {response.text[:300]}",
            request_id=_request_id(response),
        )
    try:
        return response.json()
    except ValueError as exc:
        raise GroupFileError(
            stage,
            f"非 JSON 响应：{response.text[:200]}",
            request_id=_request_id(response),
        ) from exc


def _safe_name(name):
    name = str(name or "").strip().rstrip(".")
    for char in '\t*"<>|':
        name = name.replace(char, "_")
    return name or "日报附件"


def conversation_space(token, open_conversation_id, union_id):
    """取群会话文件空间 spaceId。"""
    response = requests.post(
        f"{BASE}/v1.0/convFile/conversations/spaces/query",
        params={"unionId": union_id},
        headers=_headers(token),
        json={"openConversationId": open_conversation_id},
        timeout=20,
    )
    data = _json(response, "space")
    space_id = (data.get("space") or {}).get("spaceId")
    if not space_id:
        raise GroupFileError(
            "space", f"未返回 spaceId：{data}", request_id=_request_id(response)
        )
    return str(space_id)


def publish_group_file(
    token, *, open_conversation_id, union_id, file_name, blob, space_id=None
):
    """上传并发送为群文件卡片；返回群文件信息。

    源文件与目标群空间相同时，send 会复制出一份新文件；这里在发送成功后
    删除源副本，避免群空间堆积两份。删除失败只记日志，不影响已发送的卡片。

    space_id 由 DingtalkGroupConfig.storage_space_id 显式指定，避免测试群和
    正式群的文件空间混用；留空时才按 openConversationId 自动查询。
    """
    file_name = _safe_name(file_name)
    space_id = str(space_id or "") or conversation_space(
        token, open_conversation_id, union_id
    )
    size = len(blob)
    md5 = hashlib.md5(blob).hexdigest()

    response = requests.post(
        f"{BASE}/v1.0/storage/spaces/{space_id}/files/uploadInfos/query",
        params={"unionId": union_id},
        headers=_headers(token),
        json={
            "protocol": "HEADER_SIGNATURE",
            "multipart": False,
            "option": {
                "storageDriver": "DINGTALK",
                "preCheckParam": {
                    "parentId": "0",
                    "name": file_name,
                    "size": size,
                    "md5": md5,
                },
            },
        },
        timeout=30,
    )
    info = _json(response, "upload")
    upload_key = info.get("uploadKey")
    signature = info.get("headerSignatureInfo") or {}
    resource_urls = signature.get("resourceUrls") or []
    if not upload_key or not resource_urls:
        raise GroupFileError(
            "upload",
            "上传信息缺少 uploadKey/resourceUrls",
            request_id=_request_id(response),
        )

    # 坑：OSS 头签名把 Content-Type 计入待签串，必须完全不带。
    put_headers = {
        key: value
        for key, value in (signature.get("headers") or {}).items()
        if key.lower() != "content-type"
    }
    put = requests.put(
        resource_urls[0], data=blob, headers=put_headers, timeout=300
    )
    if put.status_code not in (200, 201, 204):
        raise GroupFileError(
            "upload",
            f"OSS PUT HTTP {put.status_code}: {put.text[:200]}",
            request_id=_request_id(put),
        )

    response = requests.post(
        f"{BASE}/v1.0/storage/spaces/{space_id}/files/commit",
        params={"unionId": union_id},
        headers=_headers(token),
        json={
            "uploadKey": upload_key,
            "name": file_name,
            "parentId": "0",
            "option": {
                "size": size,
                # 同日重跑命中已有源文件，不产生 (1)(2) 副本。
                "conflictStrategy": "RETURN_DENTRY_IF_EXISTS",
            },
        },
        timeout=30,
    )
    dentry = (_json(response, "commit").get("dentry") or {})
    source_id = dentry.get("id")
    if not source_id:
        raise GroupFileError(
            "commit",
            f"未返回 dentry.id：{dentry}",
            request_id=_request_id(response),
        )

    response = requests.post(
        f"{BASE}/v1.0/convFile/conversations/files/send",
        params={"unionId": union_id},
        headers=_headers(token),
        json={
            "spaceId": space_id,
            "dentryId": source_id,
            "openConversationId": open_conversation_id,
        },
        timeout=30,
    )
    group_file = (_json(response, "send").get("file") or {})
    group_id = group_file.get("id")
    if not group_id:
        raise GroupFileError(
            "send",
            f"未返回 file.id：{group_file}",
            request_id=_request_id(response),
        )

    if str(group_id) != str(source_id):
        try:
            delete = requests.delete(
                f"{BASE}/v1.0/storage/spaces/{space_id}/dentries/{source_id}",
                params={"unionId": union_id, "toRecycleBin": "true"},
                headers=_headers(token, json_body=False),
                timeout=30,
            )
            if delete.status_code >= 400:
                logger.warning(
                    "群文件源副本删除失败 dentry=%s HTTP=%s requestId=%s",
                    source_id,
                    delete.status_code,
                    _request_id(delete),
                )
        except Exception:
            logger.exception("群文件源副本删除异常 dentry=%s", source_id)

    return {
        "spaceId": space_id,
        "sourceDentryId": str(source_id),
        "groupId": str(group_id),
        "groupName": group_file.get("name") or file_name,
        "size": size,
        "md5": md5,
    }
