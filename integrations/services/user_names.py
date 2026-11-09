"""钉钉审批发起人姓名解析：优先通讯录接口，其次审批标题前缀。

`topapi/processinstance/get` 只返回 originator_userid，不返回 originator_name，
历史同步因此把空字符串写进了库。姓名统一在这里解析并缓存，网络或权限失败时
只降级、不阻断同步；审批标题固定为「XXX提交的<模板名>」，可作为兜底来源。
"""

import logging
import re

logger = logging.getLogger("integrations")

_TITLE_ORIGINATOR = re.compile(r"^\s*(?P<name>[^，,。]{1,40}?)提交的")


def name_from_title(title):
    """从「张三提交的付款申请」提取「张三」；无法识别时返回空串。"""
    if not isinstance(title, str):
        return ""
    match = _TITLE_ORIGINATOR.match(title)
    return match.group("name").strip() if match else ""


class UserNameDirectory:
    """按 userid 查姓名并缓存，一个客户端（钉钉应用）对应一个实例。"""

    def __init__(self, client):
        self.client = client
        self._cache = {}

    def name_for(self, userid):
        userid = str(userid or "").strip()
        if not userid:
            return ""
        if userid in self._cache:
            return self._cache[userid]
        try:
            name = self.client.get_user_name(userid) or ""
        except Exception as exc:  # 用户目录不可用不能阻断审批同步
            logger.warning("钉钉用户姓名查询失败 userid=%s：%s", userid, exc)
            name = ""
        self._cache[userid] = name
        return name

    def originator_name(self, raw):
        """审批详情 → 发起人姓名；已存姓名 > 通讯录 > 标题前缀。"""
        raw = raw or {}
        name = str(raw.get("originator_name") or "").strip()
        if name:
            return name
        name = self.name_for(raw.get("originator_userid"))
        return name or name_from_title(raw.get("title"))


def resolve_originator_name(raw, name_resolver=None):
    """name_resolver 为接收 raw 的可调用对象（如 UserNameDirectory.originator_name）。"""
    if name_resolver is not None:
        name = str(name_resolver(raw) or "").strip()
        if name:
            return name
    raw = raw or {}
    return (
        str(raw.get("originator_name") or "").strip()
        or name_from_title(raw.get("title"))
    )
